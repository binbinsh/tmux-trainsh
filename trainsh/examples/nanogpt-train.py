from trainsh.pyrecipe import *

recipe(
    "nanogpt-train",
    executor="thread_pool",
    workers=4,
    callbacks=["console", "sqlite"],
)

var("REPO_URL", "https://github.com/karpathy/nanoGPT.git")
var("WORKDIR", "/workspace/nanoGPT")
var("MODEL_OUT", "out-shakespeare")
var("MAX_ITERS", "5000")
var("BLOCK_SIZE", "256")
var("BATCH_SIZE", "64")
var("N_LAYER", "6")
var("N_HEAD", "6")
var("N_EMBD", "384")
var("LOCAL_OUTPUT", "./nanogpt-output")
host("gpu", "placeholder")

pick = vast_pick(host="gpu", num_gpus=1, min_gpu_ram=16)
ready = vast_wait(timeout="5m", after=pick)
work = session("work", on="gpu", after=ready)
clone = work(
    "git clone $REPO_URL $WORKDIR 2>/dev/null || (cd $WORKDIR && git pull)",
    after=ready,
)
deps = work(
    "pip install torch numpy transformers datasets tiktoken wandb tqdm",
    after=clone,
)
prepare = work(
    "cd $WORKDIR/data/shakespeare_char && python prepare.py",
    after=deps,
)
train = work.bg(
    "cd $WORKDIR && python train.py config/train_shakespeare_char.py "
    "--block_size=$BLOCK_SIZE --batch_size=$BATCH_SIZE --n_layer=$N_LAYER "
    "--n_head=$N_HEAD --n_embd=$N_EMBD --max_iters=$MAX_ITERS "
    "--out_dir=$MODEL_OUT 2>&1 | tee $WORKDIR/train.log",
    after=prepare,
)
done = work.wait("step $MAX_ITERS:", timeout="2h", after=train)
sample = work(
    "cd $WORKDIR && python sample.py --out_dir=$MODEL_OUT --num_samples=1 --max_new_tokens=200",
    after=done,
)
pull_model = transfer(
    "@gpu:$WORKDIR/$MODEL_OUT",
    "$LOCAL_OUTPUT/model",
    after=sample,
)
pull_log = transfer(
    "@gpu:$WORKDIR/train.log",
    "$LOCAL_OUTPUT/train.log",
    after=pull_model,
)
stop = vast_stop(after=pull_log)
work.close(after=stop)
