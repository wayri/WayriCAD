"""Read reviews, inspect work boards, locate anchors and explicitly publish comments."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import subprocess
import sys

from .session import ReviewSession


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--settings', type=Path, help='Private settings JSON, required for provider/cache commands')
    commands = parser.add_subparsers(dest='command', required=True)
    desktop = commands.add_parser('open', help='Open the native Review workspace using this terminal\'s existing authentication')
    desktop.add_argument('--board', type=Path, help='Optional saved design from the launching project')
    auth = commands.add_parser('check-login', help='Verify the existing CLI session without signing in or exposing account data')
    auth.add_argument('--provider', choices=['github', 'gitlab'], default='gitlab')
    auth.add_argument('--host', default='https://gitlab.com')
    auth.add_argument('--diagnose', action='store_true', help='Print only a secret-free failure category')
    inspect = commands.add_parser('inspect-source', help='Check saved design against its local Git revision; no provider access')
    inspect.add_argument('design', type=Path)
    commands.add_parser('sync', help='Fetch a complete provider snapshot into the optional local cache')
    commands.add_parser('cached', help='Read explicitly unverified cached comments (cannot publish or navigate)')
    commands.add_parser('boards', help='List GitLab board names or return the GitHub Projects browser link')
    locate = commands.add_parser('locate', help='Fetch provider anchor and select its object in the originating PCB editor')
    locate.add_argument('id')
    post = commands.add_parser('post', help='Preview a comment; --publish posts it once to the provider')
    post.add_argument('--body-file', type=Path, required=True)
    post.add_argument('--anchor-file', type=Path, help='KiView v1 anchor; defaults to this file scope')
    post.add_argument('--reply-to')
    post.add_argument('--publish', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.command == 'check-login':
            from .providers import verify_login, login_status
            if args.diagnose:
                result = login_status(args.provider, args.host)
                print(json.dumps(result))
                return 0 if result['authenticated'] else 2
            verify_login(args.provider, args.host)
            print(json.dumps(dict(authenticated=True, provider=args.provider)))
            return 0
        if args.command == 'open':
            return open_workspace(args, list(sys.argv[1:] if argv is None else argv))
        if args.command == 'inspect-source':
            from .model import run, saved_context
            design = args.design.resolve()
            root = Path(run(['git', 'rev-parse', '--show-toplevel'], cwd=design.parent))
            revision = run(['git', 'rev-parse', 'HEAD'], cwd=root)
            relative = design.relative_to(root).as_posix()
            path, digest = saved_context(root, dict(repository='local/saved-source', ref=revision, file=relative))
            print(json.dumps(dict(status='saved revision match / no provider connection',
                                  file=relative, ref=revision, source_sha256=digest)))
            return 0
        if args.settings is None:
            raise ValueError('Choose --settings for provider/cache commands.')
        if args.settings.stat().st_size > 64000:
            raise ValueError('Settings exceed 64 KiB.')
        settings = json.loads(args.settings.read_text(encoding='utf-8'))
        session = ReviewSession(settings)
        if args.command == 'boards':
            result = session.provider.boards()
        elif args.command == 'cached':
            result = dict(status='cached / unverified', comments=session.cached())
        elif args.command == 'sync':
            result = dict(status='synced', comments=session.refresh(), participants=session.participants)
        elif args.command == 'locate':
            session.refresh()
            result = session.locate(args.id)
        else:
            if args.body_file.stat().st_size > 16000:
                raise ValueError('Comment text exceeds the supported size.')
            text = args.body_file.read_text(encoding='utf-8')
            target = session.scope
            if args.anchor_file:
                if args.anchor_file.stat().st_size > 32000:
                    raise ValueError('Anchor file exceeds 32 KiB.')
                target = json.loads(args.anchor_file.read_text(encoding='utf-8'))
            from .model import markdown, note
            preview = markdown(note(text, target, reply_to=args.reply_to))
            if not args.publish:
                result = dict(status='preview / unpublished', providerUrl=session.provider.web_url, markdown=preview)
            else:
                session.refresh()
                result = dict(status='published', id=session.publish(text, target, reply_to=args.reply_to), providerUrl=session.provider.web_url)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, RuntimeError, KeyError, subprocess.SubprocessError) as error:
        print('Review: ' + str(error), file=sys.stderr)
        return 2


def open_workspace(args, argv):
    """Preserve the caller's authentication context; never install or transfer credentials."""
    try:
        import wx
    except ImportError:
        from wayricad_runtime.runtime_setup import native_python, child_environment
        runtime = native_python()
        if runtime is None:
            raise RuntimeError('Open Review with a Python runtime supplying wx, such as KiCad Python. No new runtime was installed.')
        bootstrap = (
            'import importlib,sys,types;from pathlib import Path;'
            'root=Path(sys.argv[1]);sys.path.insert(0,str(root));sys.path.insert(0,str(root.parent));'
            "name='wayricad_review_desktop';package=types.ModuleType(name);package.__path__=[str(root)];"
            'sys.modules[name]=package;module=importlib.import_module(name+".cli");'
            'raise SystemExit(module.main(sys.argv[2:]))'
        )
        process = subprocess.run([str(runtime), '-I', '-c', bootstrap, str(Path(__file__).parent), *argv],
                                 env=child_environment(), stdin=subprocess.DEVNULL,
                                 creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        return process.returncode
    settings = None
    if args.settings:
        if args.settings.stat().st_size > 64000:
            raise ValueError('Settings exceed 64 KiB.')
        settings = json.loads(args.settings.read_text(encoding='utf-8'))
        if not isinstance(settings, dict):
            raise ValueError('Settings must be a JSON object.')
    from .conversation_ui import ConversationPane
    app = wx.GetApp() or wx.App(False)
    frame = ConversationPane(args.board, settings=settings)
    frame.Show()
    app.MainLoop()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
