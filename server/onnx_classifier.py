import json
import logging
import os
import re
from typing import Optional, Tuple
import numpy as np
import onnxruntime as ort

logger = logging.getLogger("gambling_filter.onnx")

class DomainClassifierONNX:
    """Fast, embedded ONNX Runtime classifier for gambling domain detection."""

    def __init__(self, model_dir: Optional[str] = None):
        if model_dir is None:
            model_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")

        self.model_path = os.path.join(model_dir, "domain_classifier.onnx")
        self.vocab_path = os.path.join(model_dir, "vectorizer_vocab.json")
        self.session = None
        self.vocabulary = {}
        self.idf = None
        self.ngram_range = (3, 4)
        self.is_ready = False

        self._load()

    def _load(self):
        if not os.path.exists(self.model_path) or not os.path.exists(self.vocab_path):
            logger.warning(f"ONNX model or vocabulary not found in {os.path.dirname(self.model_path)}")
            return

        try:
            with open(self.vocab_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.vocabulary = data["vocabulary"]
                self.idf = np.array(data["idf"], dtype=np.float32)
                self.ngram_range = tuple(data.get("ngram_range", [3, 4]))

            opts = ort.SessionOptions()
            opts.intra_op_num_threads = 1
            opts.inter_op_num_threads = 1
            self.session = ort.InferenceSession(
                self.model_path,
                sess_options=opts,
                providers=["CPUExecutionProvider"]
            )
            self.input_name = self.session.get_inputs()[0].name
            self.is_ready = True
            logger.info(f"ONNX DomainClassifier initialized successfully ({len(self.vocabulary)} features)")
        except Exception as e:
            logger.error(f"Failed to load ONNX model: {e}")
            self.is_ready = False

    def _extract_char_wb_ngrams(self, text: str) -> list[str]:
        """Extracts character n-grams within word boundaries (char_wb)."""
        ngrams = []
        min_n, max_n = self.ngram_range
        # Split text into word tokens
        words = re.findall(r"\b\w+\b", text.lower())
        for w in words:
            w_padded = f" {w} "
            w_len = len(w_padded)
            for n in range(min_n, min_n + (max_n - min_n + 1)):
                for i in range(w_len - n + 1):
                    ngrams.append(w_padded[i : i + n])
        return ngrams

    def transform(self, domain: str) -> np.ndarray:
        """Converts a domain string into a normalized TF-IDF feature vector."""
        features = np.zeros(len(self.vocabulary), dtype=np.float32)
        ngrams = self._extract_char_wb_ngrams(domain)
        if not ngrams:
            return features.reshape(1, -1)

        # Count frequencies
        for gram in ngrams:
            if gram in self.vocabulary:
                idx = self.vocabulary[gram]
                features[idx] += 1.0

        # Multiply by IDF
        if self.idf is not None:
            features = features * self.idf

        # L2 normalize
        norm = np.linalg.norm(features)
        if norm > 0:
            features = features / norm

        return features.reshape(1, -1)

    def predict(self, domain: str, threshold: float = 0.6) -> Tuple[bool, float]:
        """Returns (is_gambling, probability_score)."""
        if not self.is_ready or self.session is None:
            return False, 0.0

        clean_domain = re.sub(r"^https?://", "", domain).split("/")[0].lower().rstrip(".")
        vector = self.transform(clean_domain)

        try:
            outputs = self.session.run(None, {self.input_name: vector})
            prob_dict = outputs[1][0]
            prob = prob_dict.get(1, 0.0) if isinstance(prob_dict, dict) else float(prob_dict[1])
            is_gambling = prob >= threshold
            return is_gambling, prob
        except Exception as e:
            logger.error(f"ONNX inference failed for {domain}: {e}")
            return False, 0.0


# Global singleton instance
onnx_classifier = DomainClassifierONNX()
