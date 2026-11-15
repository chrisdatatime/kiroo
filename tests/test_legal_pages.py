"""Páginas /termos e /privacidade (layout novo): estrutura, links, CSP, placeholders e versão."""

from __future__ import annotations

import re
from html.parser import HTMLParser

import pytest

from studio.accounts import TERMS_VERSION
from studio.config import load_settings
from studio.web.server import LEGAL_ASSETS, STATIC, App

BASE = {"Host": "127.0.0.1:8765"}
SECTIONS = {"/termos": [f"s{i}" for i in range(1, 12)], "/privacidade": [f"p{i}" for i in range(1, 11)]}
# Placeholders do conteúdo-base, na ordem em que aparecem (renderizados como <mark class="ph">, com os colchetes).
PLACEHOLDERS = {
    "/termos": ["CIDADE/UF DA SEDE — confirmar", "PRAZO — definir com o advogado",
                "REGRA PARA CRÉDITOS JÁ USADOS — definir com o advogado", "LICENÇA E TITULARIDADE — revisar com o advogado",
                "CIDADE/UF", "REVISAR FORO COM O ADVOGADO — o consumidor também pode acionar o foro do próprio domicílio"],
    "/privacidade": ["CIDADE/UF DA SEDE — confirmar", "+ PRAZO após a exclusão", "PRAZO — definir", "PRAZO — definir",
                     "PRAZO — definir", "BASE LEGAL DA TRANSFERÊNCIA INTERNACIONAL — revisar com o advogado",
                     "PRAZO DE RESPOSTA — proposta: 15 dias", "PRAZOS E REGRAS DE BACKUP — definir com o advogado",
                     "CONFIRMAR A LISTA DE COOKIES E ARMAZENAMENTO LOCAL"],
}
PAGES = list(SECTIONS)


class Doc(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags, self.ids, self.hrefs, self.srcs, self.scripts, self.versions, self.marks = [], set(), [], [], [], [], []
        self._script = self._mark = self._ver = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self.tags.append((tag, a))
        if "id" in a:
            self.ids.add(a["id"])
        if tag in ("a", "link") and "href" in a:
            self.hrefs.append(a["href"])
        if "src" in a:
            self.srcs.append(a["src"])
        if tag == "script":
            self._script = [a, ""]
        if tag == "mark" and a.get("class") == "ph":
            self._mark = ""
        if "data-terms-version" in a:
            self._ver = ""

    def handle_endtag(self, tag):
        if tag == "script" and self._script:
            self.scripts.append(tuple(self._script)); self._script = None
        if tag == "mark" and self._mark is not None:
            self.marks.append(self._mark); self._mark = None
        if tag == "span" and self._ver is not None:
            self.versions.append(self._ver); self._ver = None

    def handle_data(self, data):
        for k in ("_mark", "_ver"):
            if getattr(self, k) is not None:
                setattr(self, k, getattr(self, k) + data)
        if self._script:
            self._script[1] += data


@pytest.fixture
def app(settings, tmp_path):
    loader = lambda: load_settings(env_file=tmp_path / "none.env", data_dir=settings.data_dir, assets_dir=settings.assets_dir,
                                   profiles_dir=settings.profiles_dir)
    return App(8765, settings_loader=loader, sim_pacing=False)


def get(app, path):
    r = app.handle("GET", path, BASE, b"")
    return r, (r.body.decode("utf-8") if r.body else "")


def parse(app, path) -> tuple[str, Doc]:
    r, html = get(app, path)
    assert r.status == 200 and r.content_type.startswith("text/html")
    d = Doc(); d.feed(html)
    return html, d


@pytest.mark.parametrize("path", PAGES)
def test_structure(app, path):
    html, d = parse(app, path)
    assert '<html lang="pt-BR">' in html
    assert [t for t, _ in d.tags].count("h1") == 1
    for tag in ("header", "main", "footer"):
        assert any(t == tag for t, _ in d.tags), tag
    assert any(t == "nav" and ("aria-label" in a or "aria-labelledby" in a) for t, a in d.tags)
    assert 'href="#conteudo"' in html and "conteudo" in d.ids    # skip link
    sections = [a["id"] for t, a in d.tags if t == "section" and a.get("class") == "sec"]
    assert sections == SECTIONS[path]
    assert re.search(r'<meta name="description" content="[^"]+">', html) and "<title>" in html


@pytest.mark.parametrize("path", PAGES)
def test_links_resolve(app, path):
    _, d = parse(app, path)
    for href in d.hrefs:
        if href.startswith("#"):
            assert href[1:] in d.ids, href
        elif href.startswith("mailto:"):
            assert href in ("mailto:suporte@kiroo.io", "mailto:privacidade@kiroo.io"), href
        else:
            assert href.startswith("/") and not href.startswith("//"), href
    assert {"/", "/termos", "/privacidade"} <= set(d.hrefs)
    for href in {h for h in d.hrefs if h in LEGAL_ASSETS or h in SECTIONS}:
        assert get(app, href)[0].status == 200, href


@pytest.mark.parametrize("path", PAGES)
def test_no_external_or_inline_code(app, path):
    html, d = parse(app, path)
    assert not re.search(r"https?://", html)                    # nada externo (fonte, CDN, imagem)
    assert "<style" not in html and " style=" not in html       # estilo só no arquivo compartilhado
    assert d.scripts and all(a.get("src", "").startswith("/legal/") and not body.strip() for a, body in d.scripts)
    for src in d.srcs:
        r = app.handle("GET", src, BASE, b"")
        assert r.status == 200, src


@pytest.mark.parametrize("path", PAGES)
def test_placeholders_are_marked(app, path):
    html, d = parse(app, path)
    assert d.marks == [f"[[{p}]]" for p in PLACEHOLDERS[path]]
    assert html.count("[[") == len(PLACEHOLDERS[path])          # nenhum "[[" fora de um <mark class="ph">


@pytest.mark.parametrize("path", PAGES)
def test_version_matches_terms_version(app, path):
    _, d = parse(app, path)
    assert d.versions and set(d.versions) == {TERMS_VERSION}


def test_legal_assets_served_and_small(app):
    for path, ctype in LEGAL_ASSETS.items():
        r = app.handle("GET", path, BASE, b"")
        assert r.status == 200 and r.content_type == ctype, path
    assert (STATIC / "legal/legal.css").stat().st_size < 20 * 1024
    assert (STATIC / "legal/legal.js").stat().st_size < 3 * 1024
    css = (STATIC / "legal/legal.css").read_text(encoding="utf-8")
    assert "@import" not in css and "url(" not in css               # sem fonte/imagem externa
    assert app.handle("GET", "/legal/../accounts.py", BASE, b"").status != 200
