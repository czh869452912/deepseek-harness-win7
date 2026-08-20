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
        choices=["minimal", "standard", "creative", "极简模式", "标准模式", "创造模式"],
        default="standard",
        help="Agent preset mode: standard (标准模式), minimal (极简模式), or creative (创造模式)"
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
        "--web",
        action="store_true",
        help="Launch DeepSeek Harness Web GUI in browser"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Web GUI server port (default: 8080)"
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Web GUI server bind host (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Do not automatically open browser on Web GUI launch"
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
        patch_file=args.patch,
        enable_web=args.web,
        web_host=args.host,
        web_port=args.port,
    )

    if args.dump_config:
        plugins = ctx.list_plugins()
        print("=== DeepSeek Harness Win7 Cordis Configuration Dump ===")
        print(yaml.dump(plugins, allow_unicode=True))
        return

    llm_svc = ctx.get("llm")
    effective_base_url = llm_svc.resolve_base_url() if llm_svc else args.base_url
    effective_model = llm_svc.resolve_model(args.model) if llm_svc else args.model

    print(f"=== DeepSeek Harness Win7 (Mode: {args.mode}) ===")
    print(f"Base URL: {effective_base_url}")
    print(f"Model: {effective_model}")
    print(f"Loaded plugins: {[p['id'] for p in ctx.list_plugins()]}")
    print(f"Registered tools: {[t.name for t in ctx.tools.list_tools()]}")
    print("---------------------------------------------------------")

    agent_loop = ctx.get("agent_loop")

    if args.web:
        web_server = ctx.get("web_server")
        if web_server:
            await web_server.start()
            url = f"http://{args.host}:{web_server.port}"
            print(f"\n[DeepSeek Harness Web] GUI is running at: {url}")
            print("Press Ctrl+C to stop the Web server.\n")
            if not args.no_open:
                import webbrowser
                try:
                    webbrowser.open(url)
                except Exception:
                    pass
            stop_event = asyncio.Event()
            try:
                await stop_event.wait()
            except (asyncio.CancelledError, KeyboardInterrupt):
                print("\n[DeepSeek Harness Web] Stopping Web GUI server...")
            finally:
                await web_server.stop()
        return

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
