# MVP: Mock indexer service
from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route('/index', methods=['POST'])
def index():
    # In MVP, just echo back
    data = request.json
    return jsonify({'indexed': True, 'content': data.get('content', '')})

if __name__ == '__main__':
    app.run(port=5002, host='127.0.0.1')
