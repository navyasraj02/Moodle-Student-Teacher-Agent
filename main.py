"""
CLI entry point for Moodle Student-Teacher Agent System
Usage:
    python main.py --agent student
    python main.py --agent teacher
"""
import argparse
import asyncio
import sys
from dotenv import load_dotenv
from utils import setup_logging

# Load environment variables
load_dotenv()

def main():
    parser = argparse.ArgumentParser(
        description="Autonomous Moodle Agent (Student or Teacher)"
    )
    parser.add_argument(
        "--agent",
        type=str,
        required=True,
        choices=["student", "teacher"],
        help="Agent type to run"
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run browser in headless mode (no GUI)"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )
    
    args = parser.parse_args()
    
    # Setup logging
    logger = setup_logging(debug=args.debug)
    logger.info(f"Starting {args.agent} agent...")
    
    # Import and create agent
    from agents import create_agent
    
    agent = create_agent(args.agent, headless=args.headless)
    
    # Run agent
    try:
        asyncio.run(agent.run())
    except KeyboardInterrupt:
        logger.info("Agent interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Agent failed: {e}")
        if args.debug:
            import traceback
            traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
