from waitress import serve
from app import app

if __name__ == '__main__':
    print("Servidor D.A.S.H a correr na rede...")
    serve(app, host='0.0.0.0', port=5000)