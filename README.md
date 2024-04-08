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

python yarb_periodic.py --help  # for options
```

### Run as `systemd` service

See full [manual](https://linuxhandbook.com/create-systemd-services/). Example setup:

1. Create `systemd` service

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
ExecStart=/full/path/to/venv/bin/python /path/to/yarb_periodic.py --workers 10 --backups-dir /path/to/backups/dir

[Install]
WantedBy=multi-user.target
```

2. Create `.conf` configuration to pass environment variable with Redis URL

```sh
sudo systemctl edit yarb.service
```

Paste something like

```
[Service]
Environment="REDIS_URL=rediss://username:password@redis-host.com:6379"
```

3. Start the service and check everything is working

```sh
sudo systemctl start yarb.service

# check status
sudo systemctl status yarb.service  

# to view live logs
journalctl -u yarb.service -f  
```

4. Enable service so that it is restarted on reboot

```sh
sudo systemctl enable yarb.service
```

## Aux scripts

After dumping remote Redis, you can load the dump into local instance and compare it with prod.
This script will go through local keys and check corresponding remote values, printing any changes.

```bash
REDIS_URL=my-prod-redis:12345 python diff_redis_with_local.py
```

`yarb_periodic.py` stores metadata for each backup in a JSON file. To visualize some trends
in this metadata, use `visualize_metadata.py`.
