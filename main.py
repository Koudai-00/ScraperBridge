from flask import render_template
from app import app

@app.route('/')
def index():
    """Main test interface for the SNS metadata extractor"""
    return render_template('index.html')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
