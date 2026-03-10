# Pricing

Inspect exchange rates and estimate costs.

## When to use it

- Convert costs between currencies.
- Estimate run costs in scripts or ad hoc usage.

## Command

```bash
train pricing --help
```

## CLI help output

```text
usage: train pricing [-h] {rates,currency,colab,vast,convert} ...

Manage pricing and currency conversion

positional arguments:
  {rates,currency,colab,vast,convert}
                        Pricing commands
    rates               Show/refresh exchange rates
    currency            Get/set display currency
    colab               Colab pricing calculator
    vast                Show Vast.ai instance costs
    convert             Convert between currencies

options:
  -h, --help            show this help message and exit
```
