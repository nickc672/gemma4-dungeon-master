"""
# Run and get both JSON + HTML
python3 -m benchmark.runner --model gpt-oss:20b

# Run and skip the HTML (JSON only)
python3 -m benchmark.runner --model gpt-oss:20b --no-html

# Run specific tests only
python3 -m benchmark.runner --model gpt-oss:20b --tests intent mechanics_phase --no-html





# Generating a comparison report later:
python3 -m benchmark.report \
  output/20260305_123456_gpt-oss_20b_results.json \
  output/20260305_130000_llama3.1_70b_results.json \
  output/20260305_131500_gpt-oss_120b _results.json

# Auto-pick the N most recent results in the output directory: ()
python3 -m benchmark.report --latest 3

# Explicit json files with custom output path:
python3 -m benchmark.report output/a.json output/b.json --output my_comparison.html

Latest with custom output path:
python3 -m benchmark.report --latest 3 --output my_comparison.html
"""