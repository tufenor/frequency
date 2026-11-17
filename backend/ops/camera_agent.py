"""Local camera bridge."""
import argparse
import base64
import json
import time
import urllib.request
import cv2

def send_frame(api_url, reader_key, frame):
    ok, encoded = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 82])
    if not ok:
        raise RuntimeError('frame_encode_failed')
    body = json.dumps({'foto_base64': base64.b64encode(encoded.tobytes()).decode('ascii')}).encode('utf-8')
    req = urllib.request.Request(api_url, data=body, method='POST')
    req.add_header('Content-Type', 'application/json')
    req.add_header('X-Reader-Key', reader_key)
    with urllib.request.urlopen(req, timeout=8) as response:
        return json.loads(response.read().decode('utf-8'))

parser = argparse.ArgumentParser(description='Ponte local de câmera sem fio')
parser.add_argument('--source', required=True)
parser.add_argument('--reader-key', required=True)
parser.add_argument('--api-url', default='http://127.0.0.1:8000/acesso/facial')
parser.add_argument('--interval', type=float, default=1.2)
args = parser.parse_args()
if args.interval < 0.4:
    parser.error('--interval deve ser de pelo menos 0.4 segundos')
capture = None
try:
    while True:
        if capture is None or not capture.isOpened():
            if capture is not None:
                capture.release()
            capture = cv2.VideoCapture(args.source)
            if not capture.isOpened():
                print('Câmera indisponível; tentando novamente em 5 segundos.', flush=True)
                time.sleep(5)
                continue
        ok, frame = capture.read()
        if not ok:
            capture.release()
            capture = None
            continue
        try:
            result = send_frame(args.api_url, args.reader_key, frame)
            print(json.dumps({k: result.get(k) for k in ('liberado', 'nome', 'motivo')}, ensure_ascii=False), flush=True)
        except (OSError, ValueError, RuntimeError) as error:
            print(f'API local indisponível: {error}', flush=True)
        time.sleep(args.interval)
except KeyboardInterrupt:
    pass
finally:
    if capture is not None:
        capture.release()
