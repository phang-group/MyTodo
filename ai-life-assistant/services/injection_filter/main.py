import re
from flask import Flask, request, jsonify

app = Flask(__name__)

INJECTION_PATTERNS = [
    r'(?i)ai[ -]?assistant[,:]? ',
    r'(?i)execute[ -]?this[ -]?instruction',
    r'(?i)begin operation',
    r'(?i)run[ -]?this[ -]?code',
    r'(?i)prompt injection',
]

def sanitize(text):
    for pattern in INJECTION_PATTERNS:
        text = re.sub(pattern, '[REDACTED]', text)
    return text

@app.route('/sanitize', methods=['POST'])
def sanitize_route():
    data = request.json
    content = data.get('content', '')
    sanitized = sanitize(content)
    return jsonify({'sanitized': sanitized})

if __name__ == '__main__':
    app.run(port=5001, host='127.0.0.1')
