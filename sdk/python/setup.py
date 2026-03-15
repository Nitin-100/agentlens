from setuptools import setup, find_packages

setup(
    name="agentlens",
    version="0.3.0",
    description="AI Agent Observability — monitor what your agents actually do. Works with OpenAI, Claude, Gemini, LangChain, CrewAI, Google ADK, LiteLLM, and any custom agent.",
    long_description=open("README.md", encoding="utf-8").read() if __import__("os").path.exists("README.md") else "",
    long_description_content_type="text/markdown",
    author="AgentLens",
    url="https://github.com/Nitin-100/agentlens-python",
    packages=find_packages(),
    python_requires=">=3.9",
    install_requires=[],  # Zero dependencies — stdlib only
    entry_points={
        "console_scripts": [
            "agentlens=agentlens.cli:main",
        ],
    },
    extras_require={
        "openai": ["openai>=1.0.0"],
        "anthropic": ["anthropic>=0.20.0"],
        "google": ["google-generativeai>=0.5.0"],
        "google-adk": ["google-adk>=0.1.0", "google-generativeai>=0.5.0"],
        "langchain": ["langchain-core>=0.1.0"],
        "crewai": ["crewai>=0.30.0"],
        "litellm": ["litellm>=1.0.0"],
        "all": [
            "openai>=1.0.0",
            "anthropic>=0.20.0",
            "google-generativeai>=0.5.0",
            "langchain-core>=0.1.0",
            "crewai>=0.30.0",
            "litellm>=1.0.0",
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Topic :: Software Development :: Libraries",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
    ],
    keywords="ai agents observability monitoring llm openai langchain",
)
