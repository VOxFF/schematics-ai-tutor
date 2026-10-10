# Keys

Local secrets for the backend. Everything in this directory except this README is gitignored.

| File | Contents |
|---|---|
| `apikey.txt` | The Anthropic API key, on one line |

`start.sh` reads `apikey.txt` into `ANTHROPIC_API_KEY` when that variable isn't already set by the environment or `.env`.
