import os
import requests
from flask import Flask, send_from_directory, request, jsonify

app = Flask(__name__, static_folder='static')

DEEPSEEK_API_KEY = os.environ.get('DEEPSEEK_API_KEY', '')
DEEPSEEK_URL     = 'https://api.deepseek.com/chat/completions'

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/api/programme-note', methods=['POST'])
def programme_note():
    """Proxy the DeepSeek call so the API key stays server-side."""
    if not DEEPSEEK_API_KEY:
        return jsonify({'note': ''}), 200

    data = request.get_json(silent=True) or {}
    name = data.get('name', 'an unknown composer')
    key  = data.get('key', 'C')
    mode = data.get('mode', 'minor')

    try:
        resp = requests.post(
            DEEPSEEK_URL,
            headers={
                'Content-Type':  'application/json',
                'Authorization': f'Bearer {DEEPSEEK_API_KEY}',
            },
            json={
                'model': 'deepseek-chat',
                'messages': [
                    {
                        'role': 'system',
                        'content': (
                            f'Write a single poetic sentence as a programme note for '
                            f'a new generative piece in {key} {mode} inspired by {name}. '
                            f'No preamble.'
                        )
                    },
                    {'role': 'user', 'content': 'Describe the piece.'}
                ],
                'max_tokens': 80,
                'temperature': 0.9,
            },
            timeout=10,
        )
        resp.raise_for_status()
        note = resp.json()['choices'][0]['message']['content'].strip()
        return jsonify({'note': note})
    except Exception as e:
        app.logger.warning(f'DeepSeek error: {e}')
        return jsonify({'note': ''}), 200


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
