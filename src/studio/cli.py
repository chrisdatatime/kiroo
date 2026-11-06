"""CLI operacional: `studio <comando>` (ou `python -m studio`)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .config import load_settings
from .factory import build
from .logs import setup_logging
from .models import ProductInput
from .orchestrator import OrchestratorError
from .reports import cost_summary, write_reports
from .states import PRODUCTION_LABELS, SCENE_LABELS, ProductionStatus, SceneStatus

NEXT_STEP = {
    ProductionStatus.AWAITING_REFERENCES: "corrija a ficha/referências e rode `studio update-product` + `studio run`",
    ProductionStatus.PAUSED: "resolva o motivo (ex.: `studio budget --set`) e rode `studio resume` + `studio run`",
    ProductionStatus.AWAITING_FINAL_REVIEW: "assista delivery/final.mp4 e rode `studio final <id> approve|reject`",
}


def _load_product(path: str) -> ProductInput:
    return ProductInput.model_validate_json(Path(path).read_text(encoding="utf-8"))


def _print_status(orch, pid: str) -> None:
    db = orch.db
    p = db.production(pid)
    status = ProductionStatus(p["status"])
    st = orch._storage(pid)
    mode = "SIMULADO" if p["mode"] == "simulated" else "REAL"
    print(f"Produção {pid}  [{mode}]  formato={p['format_id']}")
    print(f"  Estado: {PRODUCTION_LABELS[status]}" + (f" — {p['status_reason']}" if p["status_reason"] else ""))
    c = cost_summary(db, pid)
    print(f"  Orçamento US${c['budget_usd']:.2f} | comprometido US${orch.committed_cost(pid):.4f} | "
          f"real confirmado US${c['confirmed_real_usd']:.4f} | real a confirmar US${c['real_unconfirmed_estimate_usd']:.4f}"
          + (f" | equivalente simulado US${c['simulated_equivalent_usd']:.4f}" if c["simulated_equivalent_usd"] else ""))
    for s in db.scenes(pid):
        line = f"  Cena {s['idx']}: {SCENE_LABELS[SceneStatus(s['status'])]}"
        for kind in ("image", "video"):
            aid = s[f"current_{kind}_attempt"]
            if aid:
                a = db.attempt(aid)
                if a["output_path"]:
                    line += f"\n      {kind} #{a['attempt_no']}: {st.path(a['output_path'])}"
                else:
                    line += f"\n      {kind} #{a['attempt_no']}: {a['status']}"
        print(line)
    if status in NEXT_STEP:
        print(f"  Próximo passo: {NEXT_STEP[status]}")
    waiting = [s["idx"] for s in db.scenes(pid) if s["status"] in (SceneStatus.AWAITING_IMAGE_APPROVAL,
                                                                    SceneStatus.AWAITING_VIDEO_APPROVAL,
                                                                    SceneStatus.BLOCKED)]
    if waiting:
        print(f"  Aguardando você nas cenas {waiting}: `studio approve|reject <id> <cena> image|video`")
    print(f"  Pasta: {st.root}")


def _demo(orch, settings, args) -> str:
    from .demo import create_demo_production

    pid = create_demo_production(orch, settings, budget_usd=args.budget, format_id=args.format,
                                 art_direction=args.art, presenter=args.presenter)
    print(f"Demo SIMULADA criada: {pid}")
    for _ in range(20):
        status = orch.run(pid)
        if status != ProductionStatus.PRODUCING:
            break
        for s in orch.db.scenes(pid):
            if s["status"] == SceneStatus.AWAITING_IMAGE_APPROVAL:
                orch.approve(pid, s["idx"], "image", "aprovação automática da demo", reviewer="demo-auto")
            elif s["status"] == SceneStatus.AWAITING_VIDEO_APPROVAL:
                orch.approve(pid, s["idx"], "video", "aprovação automática da demo", reviewer="demo-auto")
    return pid


def _admin(settings, args) -> int:
    import getpass

    from .accounts import Accounts, AuthError
    from .db import Database

    db = Database(settings.db_path)
    acc = Accounts(db)
    try:
        if args.acao == "list":
            for u in db.conn.execute("SELECT u.email, u.is_platform_admin, w.name, w.mode, w.allow_real, w.monthly_cap_usd "
                                     "FROM users u JOIN workspaces w ON w.owner_id=u.id ORDER BY u.created_at"):
                print(f"{u[0]:32} {'ADMIN ' if u[1] else '      '} {u[2]:28} modo={u[3]:9} real={'sim' if u[4] else 'não'} teto=US${u[5]:.2f}")
            return 0
        if not args.email:
            print("erro: informe --email", file=sys.stderr)
            return 2
        if args.acao == "create-user":
            pw = getpass.getpass("Senha (mín. 10 caracteres, não aparece na tela): ")
            uid, wid = acc.create_user(args.email, pw, args.name, admin=args.admin)
            if args.admin:
                moved = acc.assign_orphans(wid)
                acc.set_workspace(wid, allow_real=1, credits_exempt=1)
                print(f"administrador criado; {moved} produção(ões) antigas atribuídas a ele")
            else:
                print("usuário criado (em DEMO até liberar o modo real)")
            return 0
        u = acc.user_by_email(args.email)
        if not u:
            print("erro: usuário não encontrado", file=sys.stderr)
            return 2
        wid = acc.workspaces_of(u["id"])[0]["id"]
        if args.acao in ("allow-real", "deny-real"):
            acc.set_workspace(wid, allow_real=int(args.acao == "allow-real"),
                              **({} if args.acao == "allow-real" else {"mode": "simulated"}))
            print("modo real " + ("liberado" if args.acao == "allow-real" else "bloqueado (voltou para DEMO)"))
        elif args.acao == "reset-link":
            from .runtime import ServerConfig
            cfg = ServerConfig.from_env()
            base = f"https://{cfg.public_host}" if cfg.public_host else f"http://127.0.0.1:{cfg.port}"
            print(f"link (válido 30 min): {base}/?reset={acc.start_reset(args.email)}")
        elif args.acao in ("grant-credits", "adjust-credits", "credits"):
            from .credits import Ledger, fmt
            led = Ledger(db)
            if args.acao != "credits":
                if args.credits is None:
                    print("erro: informe --credits", file=sys.stderr)
                    return 2
                kind = "grant" if args.acao == "grant-credits" else "adjust"
                led.add(wid, round(args.credits * 100), kind=kind, note=args.note or ("liberado pelo administrador"
                        if kind == "grant" else "ajuste do administrador"), by="cli")
            sm = led.summary(wid)
            print(f"saldo: {sm['balance']} créditos (reservado agora: {sm['held']})" + ("  [isento]" if sm["exempt"] else ""))
        return 0
    except ValueError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 2
    except AuthError as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 2
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="studio", description="Esteira de vídeos Shopee Vídeo")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="verifica ambiente")
    sub.add_parser("list", help="lista produções")

    def with_profiles(p):
        p.add_argument("--format", default="maos_3cenas_15s")
        p.add_argument("--art", default="cozinha_sp_alto_padrao")
        p.add_argument("--presenter", default="bia")
        return p

    p = with_profiles(sub.add_parser("new", help="cria produção a partir de uma ficha JSON"))
    p.add_argument("--product", required=True)
    p.add_argument("--budget", type=float, required=True, help="limite em US$ para esta produção")

    p = with_profiles(sub.add_parser("demo", help="produção 100%% simulada com aprovações automáticas de demo"))
    p.add_argument("--budget", type=float, default=5.0)

    p = sub.add_parser("run", help="avança a produção até o próximo portão humano")
    p.add_argument("pid")
    p.add_argument("--no-wait", action="store_true", help="não aguarda operações remotas")
    p.add_argument("--max-wait", type=float, default=None, help="segundos máximos aguardando operações remotas")

    for name in ("status", "report", "pause", "resume", "cancel"):
        sub.add_parser(name).add_argument("pid")

    for name in ("approve", "reject"):
        p = sub.add_parser(name)
        p.add_argument("pid")
        p.add_argument("scene", type=int)
        p.add_argument("stage", choices=["image", "video"])
        p.add_argument("--note", default="")
        if name == "reject":
            p.add_argument("--redo-image", action="store_true", help="reprovar vídeo refazendo também a imagem")

    p = sub.add_parser("grant", help="concede tentativas extras a uma cena bloqueada")
    p.add_argument("pid")
    p.add_argument("scene", type=int)
    p.add_argument("stage", choices=["image", "video"])
    p.add_argument("--extra", type=int, default=1)

    p = sub.add_parser("prompt", help="substitui o prompt de uma cena (invalida só dependentes)")
    p.add_argument("pid")
    p.add_argument("scene", type=int)
    p.add_argument("--image-file")
    p.add_argument("--animation-file")

    p = sub.add_parser("update-product")
    p.add_argument("pid")
    p.add_argument("--product", required=True)

    p = sub.add_parser("budget")
    p.add_argument("pid")
    p.add_argument("--set", type=float, required=True, dest="value")

    p = sub.add_parser("admin", help="contas: criar usuário, liberar modo real, link de nova senha, créditos")
    p.add_argument("acao", choices=["create-user", "allow-real", "deny-real", "reset-link", "list",
                                    "grant-credits", "adjust-credits", "credits"])
    p.add_argument("--email")
    p.add_argument("--name", default="")
    p.add_argument("--admin", action="store_true", help="administrador da plataforma (só com create-user)")
    p.add_argument("--credits", type=float, help="quantidade de créditos (grant-credits/adjust-credits; ajuste aceita negativo)")
    p.add_argument("--note", default="", help="motivo do lançamento (aparece no extrato)")

    p = sub.add_parser("ui", help="serve o escritório dos agentes (padrão: só local; ver STUDIO_HOST e docs/RUNBOOK.md)")
    p.add_argument("--port", type=int, default=None, help="padrão: STUDIO_PORT, PORT ou 8765")
    p.add_argument("--host", default=None, help="padrão: STUDIO_HOST ou 127.0.0.1 (em contêiner, 0.0.0.0)")
    p.add_argument("--no-browser", action="store_true")

    p = sub.add_parser("publish", help="coloca o estúdio na internet por um túnel da Cloudflare (cadastro só por convite)")
    p.add_argument("--port", type=int, default=None)

    p = sub.add_parser("final")
    p.add_argument("pid")
    p.add_argument("decision", choices=["approve", "reject"])
    p.add_argument("--note", default="")

    args = ap.parse_args(argv)
    overrides = {"mode": "simulated"} if args.cmd == "demo" else {}
    settings = load_settings(**overrides)
    serving = args.cmd in ("ui", "publish") and os.environ.get("STUDIO_LOG_FORMAT", "json").lower() != "text"
    setup_logging(settings.data_dir / "logs", settings.secret_values(), args.verbose, json_stdout=serving)

    if args.cmd == "doctor":
        print(f"modo: {settings.mode} | chamadas pagas permitidas: {settings.allow_paid_calls}")
        print(f"GEMINI_API_KEY definida: {'sim' if settings.gemini_api_key else 'não'}")
        print(f"ffmpeg: {settings.ffmpeg_bin or 'NÃO ENCONTRADO'}")
        print(f"ffprobe: {settings.ffprobe_bin or 'NÃO ENCONTRADO'}")
        print(f"fonte: {settings.font_file or 'NÃO ENCONTRADA'}")
        print(f"dados: {settings.data_dir} | assets: {settings.assets_dir}")
        print(f"modelos: imagem={settings.image_model}@{settings.image_size} vídeo={settings.video_model}@"
              f"{settings.video_resolution} planner={settings.planner_model} revisor={settings.reviewer_model}")
        print(f"referências pessoais: {settings.reference_root}")
        bia = settings.reference_root / "bia" / "PERFIL BIA.jpg"
        print(f"referência Bia: {'ok' if bia.exists() else 'AUSENTE em ' + str(bia) + ' (monte o volume da referência pessoal; ver docs/DOCKER.md)'}")
        from .web.server import GAME_DIST

        print(f"frontend/dist: {'ok' if (GAME_DIST / 'index.html').is_file() else 'AUSENTE em ' + str(GAME_DIST)}")
        return 0

    if args.cmd == "admin":
        return _admin(settings, args)

    if args.cmd == "ui":
        from .web.server import serve

        serve(port=args.port, open_browser=not args.no_browser, host=args.host)
        return 0

    if args.cmd == "publish":
        from .web.server import publish

        publish(port=args.port)
        return 0

    orch = build(settings)
    try:
        if args.cmd == "list":
            for r in orch.db.productions():
                print(f"{r['id']}  {r['mode']:9}  {PRODUCTION_LABELS[ProductionStatus(r['status'])]:28}  {r['created_at']}")
        elif args.cmd == "new":
            pid = orch.create_production(_load_product(args.product), format_id=args.format, art_direction=args.art,
                                         presenter=args.presenter, budget_usd=args.budget)
            print(pid)
        elif args.cmd == "demo":
            pid = _demo(orch, settings, args)
            _print_status(orch, pid)
        elif args.cmd == "run":
            orch.run(args.pid, wait=not args.no_wait, max_wait_s=args.max_wait)
            _print_status(orch, args.pid)
        elif args.cmd == "status":
            _print_status(orch, args.pid)
        elif args.cmd == "report":
            write_reports(orch.db, args.pid, orch._storage(args.pid))
            print(orch._storage(args.pid).path("reports"))
        elif args.cmd == "approve":
            orch.approve(args.pid, args.scene, args.stage, args.note)
            _print_status(orch, args.pid)
        elif args.cmd == "reject":
            orch.reject(args.pid, args.scene, args.stage, args.note, redo_image=args.redo_image)
            _print_status(orch, args.pid)
        elif args.cmd == "grant":
            orch.grant_attempts(args.pid, args.scene, args.stage, args.extra)
        elif args.cmd == "prompt":
            orch.edit_scene_prompt(
                args.pid, args.scene,
                image_prompt=Path(args.image_file).read_text(encoding="utf-8") if args.image_file else None,
                animation_prompt=Path(args.animation_file).read_text(encoding="utf-8") if args.animation_file else None)
        elif args.cmd == "update-product":
            orch.update_product(args.pid, _load_product(args.product))
        elif args.cmd == "budget":
            orch.set_budget(args.pid, args.value)
        elif args.cmd == "pause":
            orch.pause(args.pid)
        elif args.cmd == "resume":
            orch.resume(args.pid)
        elif args.cmd == "cancel":
            orch.cancel(args.pid)
        elif args.cmd == "final":
            orch.final_decision(args.pid, args.decision == "approve", args.note)
            _print_status(orch, args.pid)
    except (OrchestratorError, KeyError, ValueError) as exc:
        print(f"erro: {exc}", file=sys.stderr)
        return 2
    finally:
        orch.db.close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
