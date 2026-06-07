# TRIBE v2 Text Signatures

Standalone text-to-signature module for DopaMAXX experiments.

The module accepts raw text, builds deterministic synthetic word events, runs a
prediction backend, and returns a storage-ready JSON artifact that can be
compared with cosine similarity.

## Install

For local development with deterministic fake-backend tests:

```sh
cd ../dopamaxx-tribev2-text/tribev2_text
python -m pip install -e ".[dev]"
python -m pytest
```

For real TRIBE v2 inference:

```sh
python -m pip install -e ".[tribe]"
huggingface-cli login
```

TRIBE v2 uses gated Llama 3.2 text features. Make sure the Hugging Face account
used by `huggingface-cli login` has access to `meta-llama/Llama-3.2-3B`.

## CLI

Use the fake backend for quick shape checks:

```sh
python -m tribev2_text encode --backend fake --text "This is a post." --out a.json
python -m tribev2_text compare a.json a.json
```

Use the real backend when TRIBE v2 is installed and authenticated:

```sh
python -m tribev2_text encode \
  --text-file post.txt \
  --model-id facebook/tribev2 \
  --cache-folder ./.cache \
  --out post.signature.json
```

## Python API

```python
from tribev2_text import DeterministicFakeBackend, cosine_similarity, encode_text

signature = encode_text(
    "This is a text-only post.",
    backend=DeterministicFakeBackend(),
)

print(signature.similarity_vector)
```

## Signature Format

The JSON artifact uses schema `tribev2_text.signature.v1` and includes:

- text hash and text statistics
- backend/model metadata
- TRIBE prediction shape
- summary stats over the predicted activation
- a 1536-dimensional normalized `similarity_vector`

The 1536-dimensional vector is derived by averaging predicted cortical
activation over time, z-scoring the cortical vector, applying deterministic
signed feature hashing, and L2-normalizing the result.

