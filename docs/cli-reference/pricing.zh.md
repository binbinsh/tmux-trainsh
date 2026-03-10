# 价格

查看汇率并估算成本。

## 何时使用

- 在不同币种间换算成本。
- 在脚本或临时场景中估算运行费用。

## 命令

```bash
train pricing --help
```

## CLI 帮助输出

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
