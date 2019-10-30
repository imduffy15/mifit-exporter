# gpx-exporter

GPX Exporter enables you to turn your MiFit data into GPX files which can than be uploaded to popular platforms such as Strava.

## Usage

The GPX exporter requires a rooted android device. using ADB you must extract the MiFit database as follows:

```
$ adb shell 'db=`su -c "ls /data/data/com.xiaomi.hm.health/databases/origin_db*(_+([0-9]))-journal | tail -n 1"`; su -c "cp $db /sdcard/origin_db-journal"'
$ adb pull /sdcard/origin_db-journal ./origin_db-journal
```

Then proceed to run the tool as follows:

gpx-exporter ./origin_db-journal output.gpx

## TODO

Query the data directly from the MiFit APIs

1) Get a google authentication token for client id 571394967398-j6vs98u325la013f0ho6hehosdi2h2eb.apps.googleusercontent.com
   This can be done using https://github.com/imduffy15/token-cli
   ```
   $ token-cli target create google -t https://accounts.google.com/.well-known/openid-configuration
   $ token-cli target set google
   $ token-cli token get 571394967398-j6vs98u325la013f0ho6hehosdi2h2eb.apps.googleusercontent.com --scope openid
   ```
2) Exchange the Google Token for a MiFit token
   ```
   $ export APP_TOKEN=$(curl -H 'Content-Type: application/x-www-form-urlencoded; charset=UTF-8' --data-binary "app_version=4.0.7&country_code=GB&device_id=0&third_name=google&device_model=gpx-exporter&app_name=com.xiaomi.hm.health&code=$(token-cli token get 571394967398-j6vs98u325la013f0ho6hehosdi2h2eb.apps.googleusercontent.com --scope openid)&grant_type=request_token" --compressed 'https://account.huami.com/v2/client/login' | jq -r ".token_info.app_token")
   ```
3) Request your track ids:
	```
	$ curl -H "apptoken: $APP_TOKEN" --compressed 'https://api-mifit-de.huami.com/v1/sport/run/history.json?source=run.34.huami.com%2Crun.watch.qogir.huami.com%2Crun.28.huami.com%2Crun.watch.huami.com%2Crun.25.huami.com%2Crun.beats.huami.com%2Crun.46.huami.com%2Crun.26.huami.com%2Crun.31.huami.com%2Crun.27.huami.com%2Crun.beatsp.huami.com%2Crun.44.huami.com%2Crun.24.huami.com%2Crun.chaohu.huami.com%2Crun.43.huami.com%2Crun.wuhan.huami.com%2Crun.30.huami.com%2Crun.45.huami.com%2Crun.watch.everests.huami.com%2Crun.tempo.huami.com%2Crun.35.huami.com%2Crun.watch.everest.huami.com%2Crun.36.huami.com%2Crun.42.huami.com%2Crun.mifit.huami.com%2Crun.41.huami.com%2Crun.chongqing.huami.com%2Crun.38.huami.com%2Crun.29.huami.com%2Crun.39.huami.com%2Crun.dongtinghu.huami.com%2Crun.37.huami.com%2Crun.40.huami.com' | jq -r ".data.summary[] | {track_id: .trackid, source: .source}"
	```
	```
	export TRACK_ID="something-from-the-above-output"
	export SOURCE="something-from-the-above-output"
	```
4) Request your track:
	```
	$ curl -H "apptoken: $APP_TOKEN" --compressed "https://api-mifit-de.huami.com/v1/sport/run/detail.json?trackid=$TRACK_ID&source=$SOURCE"
	```