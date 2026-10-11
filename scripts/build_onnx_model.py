"""Script to train and export the Domain Classifier ONNX model with float vector input."""
import os
import json
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from skl2onnx import convert_sklearn
from skl2onnx.common.data_types import FloatTensorType
import onnxruntime as ort

GAMBLING_SAMPLES = [
    "bet365.com", "pokerstars.com", "stake.com", "betonline.ag", "bovada.lv",
    "draftkings.com", "fanduel.com", "888casino.com", "jackpotcity.com",
    "betfair.com", "williamhill.com", "unibet.com", "paddypower.com",
    "skybet.com", "betway.com", "ladbrokes.com", "coral.co.uk", "bwin.com",
    "casumo.com", "leovegas.com", "betvictor.com", "betfred.com", "betsson.com",
    "spinpalace.com", "royalvegascasino.com", "rubyfortune.com", "europacasino.com",
    "slotsmillion.com", "casinoluck.com", "mrgreen.com", "rizk.com", "dunder.com",
    "playamo.com", "bitstarz.com", "7bitcasino.com", "roobet.com", "rollbit.com",
    "csgoempire.com", "gamdom.com", "duelbits.com", "ggbet.com", "loot.bet",
    "betus.com.pa", "mybookie.ag", "sportsbetting.ag", "intertops.eu",
    "everygame.eu", "betmaker.ag", "gtbets.ag", "xbet.ag", "betnow.eu",
    "online-casino-games.net", "free-slots-online.org", "poker-rooms.com",
    "sportsbook-review.com", "roulette-wheel.net", "blackjack-table.com",
    "vip-casino-club.com", "mega-jackpot-slots.com", "live-dealer-baccarat.com",
    "golden-nugget-casino.com", "caesars-slots.com", "mgm-grand-betting.com",
    "harrahs-online.com", "borgata-poker.com", "wsop-online.com",
    "crypto-casino.io", "bitcoin-gambling.com", "eth-dice.com", "monero-roulette.io",
    "casino888.net", "lucky777slots.com", "pokerking.com", "winbet.com",
    "superbet.ro", "sportingbet.com", "betclic.com", "pokerstars.net",
    "1xbet.com", "22bet.com", "melbet.com", "parimatch.com", "mostbet.com",
    "pin-up.casino", "vulkan-vegas.com", "solcasino.com", "freshcasino.com",
    "jetcasino.com", "izicasino.com", "legzoca.com", "volna-casino.com",
    "casino", "bet", "poker", "slots", "roulette", "blackjack", "baccarat"
]

NON_GAMBLING_SAMPLES = [
    "google.com", "wikipedia.org", "github.com", "stackoverflow.com",
    "apple.com", "microsoft.com", "amazon.com", "netflix.com", "youtube.com",
    "facebook.com", "twitter.com", "x.com", "linkedin.com", "reddit.com",
    "cnn.com", "bbc.com", "nytimes.com", "reuters.com", "bloomberg.com",
    "espn.com", "nba.com", "fifa.com", "uefa.com", "olympics.com",
    "medium.com", "dev.to", "substack.com", "quora.com", "wordpress.com",
    "python.org", "nodejs.org", "rust-lang.org", "golang.org", "docker.com",
    "kubernetes.io", "podman.io", "fastapi.tiangolo.com", "pydantic.dev",
    "slack.com", "zoom.us", "discord.com", "telegram.org", "whatsapp.com",
    "dropbox.com", "box.com", "drive.google.com", "onedrive.live.com",
    "harvard.edu", "mit.edu", "stanford.edu", "ox.ac.uk", "cam.ac.uk",
    "nationalgeographic.com", "nature.com", "sciencedirect.com", "nih.gov",
    "weather.com", "accuweather.com", "maps.google.com", "openstreetmap.org",
    "ebay.com", "walmart.com", "target.com", "bestbuy.com", "aliexpress.com",
    "imdb.com", "rottentomatoes.com", "spotify.com", "soundcloud.com",
    "booking.com", "airbnb.com", "tripadvisor.com", "expedia.com",
    "chase.com", "bankofamerica.com", "wellsfargo.com", "paypal.com", "stripe.com",
    "khanacademy.org", "coursera.org", "edx.org", "udemy.com", "duolingo.com",
    "w3schools.com", "mozilla.org", "developer.mozilla.org", "archlinux.org",
    "ubuntu.com", "debian.org", "redhat.com", "centos.org", "fedoraproject.org"
]

def build_model():
    X_raw = GAMBLING_SAMPLES + NON_GAMBLING_SAMPLES
    y = np.array([1] * len(GAMBLING_SAMPLES) + [0] * len(NON_GAMBLING_SAMPLES))

    vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 4), min_df=1)
    X = vectorizer.fit_transform(X_raw).toarray().astype(np.float32)

    classifier = LogisticRegression(C=10.0, max_iter=1000, random_state=42)
    classifier.fit(X, y)

    # Convert classifier to ONNX
    num_features = X.shape[1]
    initial_type = [("float_input", FloatTensorType([None, num_features]))]
    onnx_model = convert_sklearn(classifier, initial_types=initial_type, target_opset=12)

    output_dir = os.path.join(os.path.dirname(__file__), "../server/models")
    os.makedirs(output_dir, exist_ok=True)
    model_path = os.path.join(output_dir, "domain_classifier.onnx")
    vocab_path = os.path.join(output_dir, "vectorizer_vocab.json")

    with open(model_path, "wb") as f:
        f.write(onnx_model.SerializeToString())

    # Save vectorizer vocabulary & idf weights
    vocab_data = {
        "vocabulary": vectorizer.vocabulary_,
        "idf": vectorizer.idf_.tolist(),
        "ngram_range": [3, 4],
        "analyzer": "char_wb"
    }
    with open(vocab_path, "w") as f:
        json.dump(vocab_data, f)

    print(f"[+] Model exported to: {model_path} ({os.path.getsize(model_path)} bytes)")
    print(f"[+] Vocabulary exported to: {vocab_path} ({len(vectorizer.vocabulary_)} features)")

    # Verify ONNX Runtime
    session = ort.InferenceSession(model_path)
    test_domains = ["pokerstars.com", "wikipedia.org", "betonline.ag", "github.com", "stake.com", "google.com", "casino-royale.test"]
    
    print("\n--- Verification Results ---")
    for d in test_domains:
        feat = vectorizer.transform([d]).toarray().astype(np.float32)
        res = session.run(None, {"float_input": feat})
        label = res[0][0]
        prob_dict = res[1][0]
        prob = prob_dict.get(1, 0.0) if isinstance(prob_dict, dict) else prob_dict[1]
        print(f"Domain: {d:<20} -> Predicted: {'GAMBLING' if label == 1 else 'SAFE':<8} (Score: {prob:.4f})")

if __name__ == "__main__":
    build_model()
