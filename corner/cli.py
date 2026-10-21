import argparse
import json
import sys
from .client import Client


def main():
    parser = argparse.ArgumentParser(description='Watch Shorts with your agent. All output is JSON.')
    commands = parser.add_subparsers(dest='command', required=True)
    start = commands.add_parser('start')
    start.add_argument('--browser', choices=['chrome', 'msedge', 'chromium'], default='chromium')
    start.add_argument('--model', choices=['tiny', 'base', 'small'], default='base')
    start.add_argument('--no-likes', action='store_true', help=argparse.SUPPRESS)
    next_command = commands.add_parser('next')
    next_command.add_argument('--wait', type=float, default=25)
    reaction = commands.add_parser('react')
    reaction.add_argument('--key', required=True)
    reaction.add_argument('--text')
    reaction.add_argument('--text-file')
    reaction.add_argument('--feedback-file', help='UTF-8 JSON: rating (1–5), would_like, would_comment, comment.')
    commands.add_parser('stop')
    commands.add_parser('status')
    commands.add_parser('library')
    args = parser.parse_args()
    try:
        client = Client(autostart=args.command == 'start')
        if args.command == 'start':
            result = client.start(args.browser, args.model)
        elif args.command == 'next':
            result = client.next(args.wait)
        elif args.command == 'react':
            from pathlib import Path
            text = Path(args.text_file).read_text(encoding='utf-8') if args.text_file else args.text
            if not text:
                raise ValueError('Provide --text or --text-file with the reaction already posted in chat.')
            feedback = json.loads(Path(args.feedback_file).read_text(encoding='utf-8-sig')) if args.feedback_file else None
            from .feedback import validate_feedback
            result = client.react(args.key, text, validate_feedback(feedback))
        else:
            result = client.request({'stop': '/api/stop', 'status': '/api/state', 'library': '/api/library'}[args.command], {} if args.command == 'stop' else None)
        print(json.dumps(result, ensure_ascii=True))
    except Exception as exc:
        print(json.dumps({'status': 'error', 'message': str(exc)}, ensure_ascii=True))
        sys.exit(1)
