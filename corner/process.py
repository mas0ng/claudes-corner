"""Isolated process lets Stop cancel downloading, decoding, or inference."""
import argparse
from .media import demo, process

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='')
    parser.add_argument('--folder', required=True)
    parser.add_argument('--model', default='base')
    parser.add_argument('--cookies')
    parser.add_argument('--demo', type=int)
    args = parser.parse_args()
    if args.demo:
        demo(args.folder, args.demo)
    else:
        process(args.url, args.folder, args.model, args.cookies)
