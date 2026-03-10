# unsloth-finetune.py

Fine-tune an Unsloth model on a Vast-backed host and collect outputs locally.

## Recipe name

```text
unsloth-finetune
```

## Show this example

```bash
train recipes show unsloth-finetune
```

## Run this example

```bash
train run unsloth-finetune
```

## Source

```python
from trainsh.pyrecipe import *

recipe(
    "unsloth-finetune",
    executor="thread_pool",
    workers=4,
    callbacks=["console", "sqlite"],
)

var("WORKDIR", "/workspace/unsloth-train")
var("MODEL_NAME", "unsloth/Qwen2.5-1.5B")
var("MAX_SEQ_LENGTH", "2048")
var("LORA_RANK", "16")
var("LORA_ALPHA", "16")
var("DATASET_NAME", "yahma/alpaca-cleaned")
var("LEARNING_RATE", "2e-4")
var("MAX_STEPS", "500")
var("BATCH_SIZE", "2")
var("GRAD_ACCUM", "4")
var("WARMUP_STEPS", "10")
var("OUTPUT_DIR", "/workspace/unsloth-output")
var("LOCAL_OUTPUT", "./unsloth-output")
host("gpu", "placeholder")

pick = vast_pick(host="gpu", num_gpus=1, min_gpu_ram=16)
ready = vast_wait(timeout="5m", after=pick)
work = session("work", on="gpu", after=ready)
workspace = work("mkdir -p $WORKDIR $OUTPUT_DIR", after=ready)
install = work(
    "pip install \"unsloth[colab-new] @ git+https://github.com/unslothai/unsloth.git\" "
    "&& pip install --no-deps trl peft accelerate bitsandbytes xformers",
    after=workspace,
)
script = work(
    '''cat > $WORKDIR/train.py <<'SCRIPT'
import os
import torch
from datasets import load_dataset
from transformers import TrainingArguments
from trl import SFTTrainer
from unsloth import FastLanguageModel

model_name = os.environ.get("MODEL_NAME", "unsloth/Qwen2.5-1.5B")
max_seq_length = int(os.environ.get("MAX_SEQ_LENGTH", "2048"))
lora_rank = int(os.environ.get("LORA_RANK", "16"))
lora_alpha = int(os.environ.get("LORA_ALPHA", "16"))
dataset_name = os.environ.get("DATASET_NAME", "yahma/alpaca-cleaned")
output_dir = os.environ.get("OUTPUT_DIR", "/workspace/unsloth-output")
max_steps = int(os.environ.get("MAX_STEPS", "500"))
learning_rate = float(os.environ.get("LEARNING_RATE", "2e-4"))
batch_size = int(os.environ.get("BATCH_SIZE", "2"))
grad_accum = int(os.environ.get("GRAD_ACCUM", "4"))
warmup_steps = int(os.environ.get("WARMUP_STEPS", "10"))

print(f"Loading model: {model_name}")
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name=model_name,
    max_seq_length=max_seq_length,
    dtype=None,
    load_in_4bit=True,
)

print("Applying LoRA adapters...")
model = FastLanguageModel.get_peft_model(
    model,
    r=lora_rank,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    lora_alpha=lora_alpha,
    lora_dropout=0,
    bias="none",
    use_gradient_checkpointing="unsloth",
    random_state=42,
)

alpaca_prompt = """Below is an instruction that describes a task, paired with an input that provides further context. Write a response that appropriately completes the request.

### Instruction:
{}

### Input:
{}

### Response:
{}"""

def formatting_prompts_func(examples):
    texts = []
    for instruction, input_text, output in zip(examples["instruction"], examples["input"], examples["output"]):
        text = alpaca_prompt.format(instruction, input_text, output) + tokenizer.eos_token
        texts.append(text)
    return {"text": texts}

print(f"Loading dataset: {dataset_name}")
dataset = load_dataset(dataset_name, split="train")
dataset = dataset.map(formatting_prompts_func, batched=True)

print("Starting training...")
trainer = SFTTrainer(
    model=model,
    tokenizer=tokenizer,
    train_dataset=dataset,
    dataset_text_field="text",
    max_seq_length=max_seq_length,
    dataset_num_proc=2,
    packing=False,
    args=TrainingArguments(
        per_device_train_batch_size=batch_size,
        gradient_accumulation_steps=grad_accum,
        warmup_steps=warmup_steps,
        max_steps=max_steps,
        learning_rate=learning_rate,
        fp16=not torch.cuda.is_bf16_supported(),
        bf16=torch.cuda.is_bf16_supported(),
        logging_steps=10,
        optim="adamw_8bit",
        weight_decay=0.01,
        lr_scheduler_type="linear",
        seed=42,
        output_dir=output_dir,
        save_strategy="steps",
        save_steps=100,
    ),
)

trainer.train()

print("Saving model...")
model.save_pretrained(f"{output_dir}/lora_model")
tokenizer.save_pretrained(f"{output_dir}/lora_model")

print("Exporting GGUF model...")
model.save_pretrained_gguf(f"{output_dir}/gguf", tokenizer, quantization_method="q4_k_m")

print(f"Training complete! Results saved to {output_dir}")
with open(f"{output_dir}/training_complete.txt", "w", encoding="utf-8") as handle:
    handle.write("done\\n")
SCRIPT''',
    after=install,
)
train = work.bg(
    "cd $WORKDIR && "
    "MODEL_NAME=$MODEL_NAME MAX_SEQ_LENGTH=$MAX_SEQ_LENGTH LORA_RANK=$LORA_RANK "
    "LORA_ALPHA=$LORA_ALPHA DATASET_NAME=$DATASET_NAME OUTPUT_DIR=$OUTPUT_DIR "
    "MAX_STEPS=$MAX_STEPS LEARNING_RATE=$LEARNING_RATE BATCH_SIZE=$BATCH_SIZE "
    "GRAD_ACCUM=$GRAD_ACCUM WARMUP_STEPS=$WARMUP_STEPS "
    "python train.py 2>&1 | tee $OUTPUT_DIR/train.log",
    after=script,
)
done = work.file("$OUTPUT_DIR/training_complete.txt", timeout="3h", after=train)
pull_lora = transfer(
    "@gpu:$OUTPUT_DIR/lora_model",
    "$LOCAL_OUTPUT/lora_model",
    after=done,
)
pull_gguf = transfer(
    "@gpu:$OUTPUT_DIR/gguf",
    "$LOCAL_OUTPUT/gguf",
    after=pull_lora,
)
pull_log = transfer(
    "@gpu:$OUTPUT_DIR/train.log",
    "$LOCAL_OUTPUT/train.log",
    after=pull_gguf,
)
stop = vast_stop(after=pull_log)
work.close(after=stop)
```
