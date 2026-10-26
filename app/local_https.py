"""TLS upstream for the isolated Windows/ngrok installer; no forwarded headers are trusted."""
import base64
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import uvicorn


def main() -> None:
    if (os.getenv('MOS_LOCAL_SETUP_ENABLED')!='true' or os.getenv('MOS_ENV')!='test'
            or os.getenv('MOS_MODEL_CALLS_ENABLED')!='false' or os.getenv('MOS_THREADS_PUBLISH_ENABLED')!='false'):
        raise RuntimeError('Controlled local setup only; model calls and publication must be disabled')
    with TemporaryDirectory() as directory:
        paths=[]
        for name in ('CERT','KEY'):
            path=Path(directory)/name.lower()
            with path.open('xb') as stream:
                os.chmod(path,0o600)
                stream.write(base64.b64decode(os.environ.pop('MOS_SETUP_TLS_'+name),validate=True))
            paths.append(str(path))
        uvicorn.run('app.main:app',host='0.0.0.0',port=8000,ssl_certfile=paths[0],ssl_keyfile=paths[1],
                    proxy_headers=False,access_log=False,timeout_keep_alive=5)


if __name__=='__main__':main()
