#!/usr/bin/env python3
import json
import os
import getpass
import sys

SECRETS_FILE = "secrets.json"
TEMPLATE_FILE = "secrets.json.template"

# Colors
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
RESET = "\033[0m"

def load_template():
    if not os.path.exists(TEMPLATE_FILE):
        print(f"{RED}Error: {TEMPLATE_FILE} not found.{RESET}")
        print("Please ensure you are in the project root directory context.")
        sys.exit(1)
    
    with open(TEMPLATE_FILE, "r") as f:
        return json.load(f)

def prompt_value(key, default_value):
    description = f"Enter value for {GREEN}{key}{RESET}"
    
    # Customize prompt for specific keys
    if "password" in key:
        description += " (Hidden input)"
    elif "SCOUT_UNIVERSE_SIZE" in key:
        description += f"\n  {YELLOW}Number of top market cap stocks to analyze (affects LLM cost). Default: 50{RESET}"
    elif "ENABLE_NEWS_ANALYSIS" in key:
         description += f"\n  {YELLOW}Enable news scanning and sentiment analysis? (true/false){RESET}"
    
    suffix = f" [{default_value}]: " if default_value else ": "
    
    print(f"\n{description}")
    
    try:
        if "password" in key or "secret" in key or "api-key" in key:
            user_input = getpass.getpass(prompt=suffix)
        else:
            user_input = input(suffix)
    except KeyboardInterrupt:
        print("\nOperation cancelled.")
        sys.exit(0)

    if not user_input.strip():
        return default_value
    
    # Type conversion for boolean and integer
    if isinstance(default_value, bool):
        return user_input.lower() in ('true', '1', 'yes', 'y')
    if isinstance(default_value, int):
        try:
            return int(user_input)
        except ValueError:
            print(f"{RED}Invalid integer. Using default: {default_value}{RESET}")
            return default_value
            
    return user_input

def main():
    print(f"{GREEN}=========================================={RESET}")
    print(f"{GREEN}   Project Prime: Secret Generator        {RESET}")
    print(f"{GREEN}=========================================={RESET}")

    if os.path.exists(SECRETS_FILE):
        print(f"{YELLOW}Warning: {SECRETS_FILE} already exists.{RESET}")
        choice = input("Overwrite? (y/N): ")
        if choice.lower() != 'y':
            print("Exiting without changes.")
            return

    template = load_template()
    new_secrets = {}

    print("\nPlease configure your environment variables and secrets.")
    print("Press Enter to use the default value (shown in brackets).")

    for key, default_val in template.items():
        new_secrets[key] = prompt_value(key, default_val)

    # Save to file
    try:
        with open(SECRETS_FILE, "w") as f:
            json.dump(new_secrets, f, indent=4)
        
        # Set permissions to 600 (read/write by owner only)
        os.chmod(SECRETS_FILE, 0o600)
        
        print(f"\n{GREEN}Success! {SECRETS_FILE} created with secure permissions (0600).{RESET}")
        print(f"Scout Universe Size: {new_secrets.get('SCOUT_UNIVERSE_SIZE')}")
        
    except Exception as e:
        print(f"{RED}Error writing {SECRETS_FILE}: {e}{RESET}")
        sys.exit(1)

if __name__ == "__main__":
    main()
