"""Real LLM clients (Claude via Vertex, Gemini via the Generative Language API).

These are the *working* backends. The legacy src/gemini/client.py talks to the
Vertex Gemini publisher endpoint, which 404s on the hackathon project; these
clients are what actually reach a model.
"""
