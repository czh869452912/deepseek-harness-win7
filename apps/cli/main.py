import argparse
import asyncio
import os
import sys
import yaml

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

from dsh.harness import build_harness


def parse_args():
    parser = argparse.ArgumentParser(
        description="DeepSeek Harness Win7 - Cordis Architecture CLI (Python 3.8.10)"
    )
    parser.add_argument(
        "-m", "--mode",
        choices=["minimal", "creative", "极简模式", "创造模式"],
        default="minimal",
        help="Agent preset mode: minimal (极简模式) or creative (创造模式)"
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="LLM API Key (or DEEPSEEK_API_KEY / OPENAI_API_KEY env / ~/.dsh/credentials.json)"
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="LLM Base URL (or DEEPSEEK_BASE_URL env / ~/.dsh/settings.json)"
    )
    parser.add_argument(
        "--model",
        default=None,
        help="LLM Model name (or DEEPSEEK_MODEL env / ~/.dsh/settings.json)"
    )
    parser.add_argument(
        "--dump-config",
        action="store_true",
        help="Dump mounted Cordis configuration tree and exit"
    )
    parser.add_argument(
        "--patch",
        help="Path to custom cordis.patch.yml file overlay"
    )
    parser.add_argument(
        "-p", "--prompt",
        help="Single input prompt to process (non-interactive mode)"
    )
    return parser.parse_args()


async def main_async():
    args = parse_args()

    # Build Cordis context
    ctx = build_harness(
        mode=args.mode,
        api_key=args.api_key,
        base_url=args.base_url,
        model=args.model,
        patch_file=args.patch
    )

    if args.dump_config:
        plugins = ctx.list_plugins()
        print("=== DeepSeek Harness Win7 Cordis Configuration Dump ===")
        print(yaml.dump(plugins, allow_unicode=True))
        return

    print(f"=== DeepSeek Harness Win7 (Mode: {args.mode}) ===")
    print(f"Base URL: {args.base_url}")
    print(f"Model: {args.model}")
    print(f"Loaded plugins: {[p['id'] for p in ctx.list_plugins()]}")
    print(f"Registered tools: {[t.name for t in ctx.tools.list_tools()]}")
    print("---------------------------------------------------------")

    agent_loop = ctx.get("agent_loop")

    if args.prompt:
        # Run single turn
        print(f"\nUser: {args.prompt}")
        response = await agent_loop.run_turn(args.prompt)
        print(f"\nAssistant:\n{response}")
        return

    # Interactive REPL mode
    print("Type your message below (or type 'exit' / 'quit' to quit):\n")
    while True:
        try:
            user_input = input("dsh> ").strip()
            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit", ":q"):
                print("Exiting DeepSeek Harness.")
                break

            print("\nProcessing...")
            response = await agent_loop.run_turn(user_input)
            print(f"\nAssistant:\n{response}\n")
        except (KeyboardInterrupt, EOFError):
            print("\nExiting.")
            break
        except Exception as e:
            print(f"\n[Error]: {e}\n")


def main():
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
