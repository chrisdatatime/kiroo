"""Servidor SMTP falso (só 127.0.0.1, sem TLS) para testar o envio ponta a ponta sem rede externa.

Entende EHLO/HELO, AUTH PLAIN e AUTH LOGIN, MAIL, RCPT, DATA, RSET, NOOP e QUIT. Guarda cada mensagem recebida
(remetente do envelope, destinatários, credencial usada e o e-mail já decodificado).
"""

from __future__ import annotations

import base64
import socketserver
import threading
from email import message_from_bytes, policy


class _Handler(socketserver.StreamRequestHandler):
    def _out(self, line: str) -> None:
        self.wfile.write((line + "\r\n").encode())
        self.wfile.flush()

    def _readline(self) -> str:
        return self.rfile.readline().decode("utf-8", "replace").rstrip("\r\n")

    def handle(self):  # noqa: C901 — protocolo mínimo
        srv = self.server
        mail_from, rcpts, auth = None, [], None
        self._out("220 fake.smtp ESMTP pronto")
        while True:
            line = self._readline()
            if not line and self.rfile.closed:
                return
            cmd = line.split(" ", 1)[0].upper()
            arg = line[len(cmd):].strip()
            if cmd in ("EHLO", "HELO"):
                self.wfile.write(b"250-fake.smtp\r\n250-AUTH PLAIN LOGIN\r\n250 8BITMIME\r\n")
                self.wfile.flush()
            elif cmd == "AUTH":
                parts = arg.split()
                if parts[0].upper() == "PLAIN":
                    raw = parts[1] if len(parts) > 1 else (self._out("334 ") or self._readline())
                    _, user, pw = base64.b64decode(raw).decode().split("\0")
                else:  # LOGIN
                    self._out("334 VXNlcm5hbWU6")
                    user = base64.b64decode(self._readline()).decode()
                    self._out("334 UGFzc3dvcmQ6")
                    pw = base64.b64decode(self._readline()).decode()
                if srv.credentials is not None and (user, pw) != srv.credentials:
                    self._out("535 credencial inválida")
                    continue
                auth = (user, pw)
                self._out("235 ok")
            elif cmd == "MAIL":
                mail_from = arg.split(":", 1)[1].split()[0].strip("<>")
                self._out("250 ok")
            elif cmd == "RCPT":
                rcpts.append(arg.split(":", 1)[1].strip().strip("<>"))
                self._out("250 ok")
            elif cmd == "DATA":
                self._out("354 fim com <CRLF>.<CRLF>")
                data = bytearray()
                while True:
                    raw = self.rfile.readline()
                    if raw in (b".\r\n", b".\n", b""):
                        break
                    if raw.startswith(b".."):
                        raw = raw[1:]
                    data += raw
                with srv.lock:
                    srv.messages.append({"from": mail_from, "to": list(rcpts), "auth": auth,
                                         "msg": message_from_bytes(bytes(data), policy=policy.default)})
                mail_from, rcpts = None, []
                self._out("250 entregue")
            elif cmd in ("RSET", "NOOP"):
                self._out("250 ok")
            elif cmd == "QUIT":
                self._out("221 tchau")
                return
            elif cmd == "STARTTLS":
                self._out("454 TLS indisponível")
            else:
                self._out("502 comando desconhecido")


class FakeSMTP(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, credentials: tuple[str, str] | None = None):
        super().__init__(("127.0.0.1", 0), _Handler)
        self.credentials = credentials
        self.messages: list[dict] = []
        self.lock = threading.Lock()
        self._t = threading.Thread(target=self.serve_forever, daemon=True)

    @property
    def port(self) -> int:
        return self.server_address[1]

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, *exc):
        self.shutdown()
        self.server_close()
