import uuid
from datetime import datetime
from flask import Flask, request, jsonify

app = Flask(__name__)

approval_db = []  # In-memory for MVP

@app.route('/stage', methods=['POST'])
def stage():
    data = request.json
    item = {
        'id': str(uuid.uuid4()),
        'type': data['type'],
        'content': data['content'],
        'confidence': data['confidence'],
        'risk': data['risk'],
        'created': datetime.now().isoformat(),
        'status': 'pending'
    }
    approval_db.append(item)
    return jsonify({'id': item['id']})

@app.route('/approve', methods=['POST'])
def approve():
    data = request.json
    for item in approval_db:
        if item['id'] == data['id']:
            item['status'] = 'approved'
            return jsonify({'status': 'approved'})
    return jsonify({'error': 'not found'}), 404

@app.route('/reject', methods=['POST'])
def reject():
    data = request.json
    for item in approval_db:
        if item['id'] == data['id']:
            item['status'] = 'rejected'
            item['reason'] = data.get('reason', None)
            return jsonify({'status': 'rejected'})
    return jsonify({'error': 'not found'}), 404

@app.route('/queue', methods=['GET'])
def queue():
    return jsonify({'queue': approval_db})

if __name__ == '__main__':
    app.run(port=5003, host='127.0.0.1')
