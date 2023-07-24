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

## Periodic backup

```sh
export REDIS_URL="rediss://:password1@redis-host.com:12345"
python yarb_periodic.py

python yarb_periodic.py --help for options
```

### Run as `systemd` service

See full [manual](https://linuxhandbook.com/create-systemd-services/). Example setup:

```sh
sudo nano /etc/systemd/system/yarb.service
```

Paste something like:

```
[Unit]
Description=Redis periodic backup
After=network.target
StartLimitIntervalSec=0

[Service]
Type=simple
Restart=always
RestartSec=1
User=my-username
ExecStart=/full/path/to/venv/bin/python /full/path/to/yarb_periodic.py --workers 5

[Install]
WantedBy=multi-user.target
```

Set `REDIS_URL` environment variable

```sh
sudo systemctl edit yarb.service
```