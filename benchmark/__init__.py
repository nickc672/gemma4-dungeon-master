"""
# Run and get both JSON + HTML
python3 -m benchmark.runner --model gpt-oss:20b

# Run and skip the HTML (JSON only)
python3 -m benchmark.runner --model gpt-oss:20b --no-html

# Run specific tests only
python3 -m benchmark.runner --model gpt-oss:20b --tests phase_one narration
The --tests choices are phase_one, narration, phase_two (any combination of those)

# Different provider
python3 -m benchmark.runner --model claude-haiku-4-5-20251001 --provider anthropic

# Generating a comparison report later:
python3 -m benchmark.report \
  output/20260517_143000_gpt-oss_20b_results.json \
  output/20260517_150000_llama3.1_70b_results.json

# Auto-pick the N most recent results in the output directory:
python3 -m benchmark.report --latest 3

Latest with custom output path:
python3 -m benchmark.report --latest 3 --output my_comparison.html
"""