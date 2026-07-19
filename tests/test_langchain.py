"""
Test script for Composio + LangChain using GitHub Models (OpenAI compatible).

Usage:
    export GITHUB_TOKEN="your_github_token"
    export COMPOSIO_API_KEY="your_composio_api_key"
    python test_langchain.py
"""

import os
import sys

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from composio import Composio
from composio_langchain import LangchainProvider

def main():
    load_dotenv()

    # Get credentials from environment
    github_token = os.getenv("GITHUB_TOKEN")
    if not github_token:
        print("Error: GITHUB_TOKEN environment variable is required.")
        sys.exit(1)

    composio_api_key = os.getenv("COMPOSIO_API_KEY")
    if not composio_api_key:
        print("Error: COMPOSIO_API_KEY environment variable is required.")
        sys.exit(1)

    print("Initializing Composio...")
    # Initialize Composio with LangchainProvider
    # This ensures session.tools() returns LangChain-compatible StructuredTool objects
    composio_client = Composio(
        provider=LangchainProvider(),
        api_key=composio_api_key
    )

    # Create or reuse a session for the user
    user_id = "user_123"
    print(f"Creating/using Composio session for user: {user_id}")
    session = composio_client.create(user_id=user_id)
    
    # Get tools for this session
    tools = session.tools()
    print(f"Loaded {len(tools)} tools from Composio.")

    print("Initializing LLM via GitHub Models...")
    # Initialize ChatOpenAI pointing to GitHub Models endpoint
    # Using gpt-4o as it's a standard model on GitHub Models
    llm = ChatOpenAI(
        model="gpt-4o", 
        api_key=github_token,
        base_url="https://models.inference.ai.azure.com",
        temperature=0.1
    )

    print("Creating LangGraph ReAct agent...")
    # Create the ReAct agent using LangGraph (recommended way for LangChain agents)
    # The agent will have access to the tools and the LLM
    agent_executor = create_react_agent(llm, tools=tools)

    # System instruction (optional, but good for setting context)
    system_prompt = "You are a helpful personal assistant. Use Composio tools to take action."

    print("\n" + "="*50)
    print("Agent is ready!")
    print("Example tasks:")
    print("  - 'Summarize my emails from today'")
    print("  - 'List all open issues on the composio github repository'")
    print("Type 'exit' or 'quit' to stop.")
    print("="*50 + "\n")

    # Interactive loop
    while True:
        try:
            user_input = input("You: ").strip()
            if user_input.lower() in ["exit", "quit"]:
                break
            if not user_input:
                continue

            print("\nAssistant is thinking...")
            
            # Prepare messages payload
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input}
            ]

            # Invoke the agent
            result = agent_executor.invoke({"messages": messages})
            
            # The result contains a list of messages. The last one is the final response.
            final_response = result["messages"][-1].content
            print(f"\nAssistant: {final_response}\n")

        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"\nError occurred: {e}\n")

if __name__ == "__main__":
    main()
