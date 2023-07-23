# yarb

Yet another Redis backup utility. Partial port of [upstash-redis-dump](https://github.com/upstash/upstash-redis-dump)
to Python 3.10+.

## Dump

```sh
pip install -r requirements.txt
export REDIS_URL="rediss://:password1@redis-host.com:12345"
python yarb.py $REDIS_URL my-dump.resp

python yarb.py --help  # for options
```

## Load

From [manual](https://redis.io/docs/manual/patterns/bulk-loading/):

```sh
cat my-dump.resp | redis-cli --pipe
```

