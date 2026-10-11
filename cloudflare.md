https://developers.cloudflare.com/email-service/api/send-emails/rest-api/

curl "https://api.cloudflare.com/client/v4/accounts/{account_id}/email/sending/send" \
  --header "Authorization: Bearer <API_TOKEN>" \
  --header "Content-Type: application/json" \
  --data '{
    "to": "recipient@example.com",
    "from": "welcome@yourdomain.com",
    "subject": "Welcome to our service!",
    "html": "<h1>Welcome!</h1><p>Thanks for signing up.</p>",
    "text": "Welcome! Thanks for signing up."
  }'
