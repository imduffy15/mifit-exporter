import array
import datetime as DT
import sqlite3
from bisect import bisect_left
from collections import namedtuple
from datetime import datetime
from itertools import accumulate
import json
import click
import xmltodict
from clickclick import AliasedGroup
from deepmerge import conservative_merger
import gpx_exporter

CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'])

NO_VALUE = -2000000
FIX_BIP_GAPS = False

output_option = click.option('-o',
                             '--output',
                             type=click.Choice(['text', 'json', 'tsv']),
                             default='text',
                             help='Use alternative output format')

RawTrackData = namedtuple('RawTrackData', [
    'start_time', 'end_time', 'cost_time', 'avg_heart_rate', 'max_heart_rate',
    'min_heart_rate', 'calorie', 'total_step', 'times', 'lat', 'lon', 'alt',
    'distance', 'distancetimes', 'hrtimes', 'hr', 'steptimes', 'stride',
    'cadence'
])
Position = namedtuple('Position', ['lat', 'lon', 'alt'])
TrackPoint = namedtuple(
    'TrackPoint', ['time', 'position', 'hr', 'stride', 'cadence', 'distance'])


class Interpolate(object):
    def __init__(self, x_list, y_list):
        intervals = zip(x_list, x_list[1:], y_list, y_list[1:])
        self.x_list = x_list
        self.y_list = y_list
        self.slopes = [(y2 - y1) // ((x2 - x1) or 1)
                       for x1, x2, y1, y2 in intervals]

    def __getitem__(self, x):
        i = bisect_left(self.x_list, x) - 1
        if i >= len(self.slopes):
            return self.y_list[-1]
        if i < 0:
            return self.y_list[0]
        return self.y_list[i] + self.slopes[i] * (x - self.x_list[i])


def print_version():
    click.echo('gpx-exporter {}'.format(gpx_exporter.__version__))


def export_all_tracks(summary, detail):
    data = {}
    with open(detail, 'r') as f:
        data = json.load(f)
    with open(summary, 'r') as f:
        conservative_merger.merge(data, json.load(f))

    export_activity(parse_activity_data(data))


def export_activity(activity):
    start_time = DT.datetime.utcfromtimestamp(activity.start_time).isoformat()
    tcx = {
        "TrainingCenterDatabase": {
            "@xmlns:ns2": "http://www.garmin.com/xmlschemas/UserProfile/v2",
            "@xmlns:ns4":
            "http://www.garmin.com/xmlschemas/ProfileExtension/v1",
            "@xmlns:ns5": "http://www.garmin.com/xmlschemas/ActivityGoals/v1",
            "@xmlns:tpx":
            "http://www.garmin.com/xmlschemas/ActivityExtension/v2",
            "@xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
            "@xmlns":
            "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2",
            "Activities": {
                "Activity": [{
                    "@Sport": "Running",
                    "Id": start_time,
                    "Lap": {
                        "@StartTime": start_time,
                        "TotalTimeSeconds": float(activity.cost_time),
                        "DistanceMeters": float(sum(activity.distance)),
                        "Calories": int(activity.calorie),
                        "AverageHeartRateBpm": {
                            "Value": int(activity.avg_heart_rate)
                        },
                        "Track": {
                            "Trackpoint": []
                        }
                    },
                    "Notes": "Synced run"
                }]
            }
        }
    }

    gpx = {
        "gpx": {
            "@xmlns": "http://www.topografix.com/GPX/1/1",
            "@xmlns:gpxdata": "http://www.cluetrust.com/XML/GPXDATA/1/0",
            "@xmlns:gpxtpx":
            "http://www.garmin.com/xmlschemas/TrackPointExtension/v1",
            "metadata": {
                "time": start_time
            },
            "trk": {
                "name": start_time,
                "type": 10,
                "trkseg": {
                    "trkpt": []
                }
            }
        }
    }

    for point in track_points(interpolate_data(activity)):
        time = datetime.utcfromtimestamp(point.time +
                                         activity.start_time).isoformat()
        tcx_trkpt = {
            "Time": time,
            "DistanceMeters": float(point.distance),
            "HeartRateBpm": {
                "@xsi:type": "HeartRateInBeatsPerMinute_t"
            },
            "Extensions": {
                "TPX": {
                    "@xmlns":
                    "http://www.garmin.com/xmlschemas/ActivityExtension/v2"
                }
            }
        }

        gpx_trkpt = {
            "ele": point.position.alt,
            "time": time,
            "@lat": point.position.lat,
            "@lon": point.position.lon,
            "extensions": {
                "gpxtpx:TrackPointExtension": {}
            }
        }

        if point.hr:
            gpx_trkpt["extensions"]['gpxtpx:TrackPointExtension'][
                'gpxtpx:hr'] = point.hr
            tcx_trkpt["HeartRateBpm"]["Value"] = point.hr

        if point.cadence:
            gpx_trkpt["extensions"]["gpxdata:cadence"] = point.cadence
            tcx_trkpt["Extensions"]["TPX"]["RunCadence"] = point.cadence

        gpx['gpx']['trk']['trkseg']['trkpt'].append(gpx_trkpt)
        tcx['TrainingCenterDatabase']['Activities']['Activity'][0][
            'Lap']['Track']['Trackpoint'].append(tcx_trkpt)

    click.echo(xmltodict.unparse(tcx, pretty=True))
    # click.echo(xmltodict.unparse(gpx, pretty=True))


def interpolate_data(track_data):
    track_times = array.array('l', accumulate(track_data.times))
    hr_times = array.array('l', accumulate(track_data.hrtimes))
    step_times = array.array('l', accumulate(track_data.steptimes))
    distance_times = array.array('l', accumulate(track_data.distancetimes))

    def change_times(times, change, time_from):
        return array.array('l', (time + change if time >= time_from else time
                                 for time in times))

    times = list(
        sorted(
            set(track_times).union(hr_times).union(step_times).union(
                distance_times)))

    if FIX_BIP_GAPS:
        time_to_trim = (times[-1] - track_data.cost_time) if track_times else 0
        while time_to_trim > 0:
            max_time = 0
            max_interval = 0
            last_time = 0
            for time in times:
                current_interval = time - last_time
                last_time = time
                if current_interval > max_interval:
                    max_interval = current_interval
                    max_time = time
            time_change = max(max_interval - time_to_trim, 1) - max_interval
            track_times = change_times(track_times, time_change, max_time)
            distance_times = change_times(distance_times, time_change,
                                          max_time)
            hr_times = change_times(hr_times, time_change, max_time)
            step_times = change_times(step_times, time_change, max_time)
            time_to_trim += time_change
            times = list(
                sorted(
                    set(track_times).union(hr_times).union(step_times).union(
                        distance_times)))

    track_data = track_data._replace(
        times=times,
        lat=interpolate_column(accumulate(track_data.lat), track_times, times),
        lon=interpolate_column(accumulate(track_data.lon), track_times, times),
        alt=interpolate_column(track_data.alt, track_times, times),
        distance=interpolate_column(accumulate(track_data.distance), distance_times,
                                    times),
        distancetimes=times,
        hrtimes=times,
        hr=interpolate_column(accumulate(track_data.hr), hr_times, times),
        steptimes=times,
        stride=interpolate_column(track_data.stride, step_times, times),
        cadence=interpolate_column(track_data.cadence, step_times, times),
    )

    return track_data


def interpolate_column(data, original_points, new_points):
    # fill gaps
    data = array.array('l', data)
    old_value = NO_VALUE
    for old_value in data:
        if old_value != NO_VALUE:
            break
    for i, value in enumerate(data):
        if value == NO_VALUE:
            data[i] = old_value
        else:
            old_value = value

    if len(new_points) == 0:
        return array.array('l', [])
    if len(original_points) == 0:
        return array.array('l', [0] * len(new_points))
    if len(original_points) == 1:
        return array.array('l', [original_points[1]] * len(new_points))
    interpolate = Interpolate(original_points, data)
    return array.array('l', (interpolate[point] for point in new_points))


def track_points(track_data):
    for time, lat, lon, alt, hr, stride, cadence, distance in zip(
            track_data.times, track_data.lat, track_data.lon, track_data.alt,
            track_data.hr, track_data.stride, track_data.cadence,
            track_data.distance):
        yield TrackPoint(time=time,
                         position=Position(lat=lat / 100000000,
                                           lon=lon / 100000000,
                                           alt=alt / 100),
                         hr=hr,
                         stride=stride,
                         cadence=cadence,
                         distance=distance)


def parse_activity_data(data):
    track_data = RawTrackData(
        start_time=int(data["trackid"]),
        end_time=int(data["end_time"]),
        cost_time=int(data["run_time"]),
        avg_heart_rate=float(data["avg_heart_rate"]),
        max_heart_rate=float(data["max_heart_rate"]),
        min_heart_rate=float(data["min_heart_rate"]),
        calorie=float(data["calorie"]),
        total_step=int(data["total_step"]),
        times=array.array('l',
                          [int(val) for val in data["time"].split(';')
                           if val] if data["time"] else []),
        lat=array.array('l', [
            int(val.split(',')[0])
            for val in data["longitude_latitude"].split(';') if val
        ] if data["longitude_latitude"] else []),
        lon=array.array('l', [
            int(val.split(',')[1])
            for val in data["longitude_latitude"].split(';') if val
        ] if data["longitude_latitude"] else []),
        alt=array.array(
            'l', [int(val) for val in data["altitude"].split(';')
                  if val] if data["altitude"] else []),
        distance=array.array('l', [
            int(val.split(',')[1]) for val in data["distance"].split(';')
            if val
        ] if data["distance"] else []),
        distancetimes=array.array('l', [
            int(val.split(',')[0] or 1) for val in data["distance"].split(';')
            if val
        ] if data["distance"] else []),
        hrtimes=array.array('l', [
            int(val.split(',')[0] or 1)
            for val in data["heart_rate"].split(';') if val
        ] if data["heart_rate"] else []),
        hr=array.array('l', [
            int(val.split(',')[1]) for val in data["heart_rate"].split(';')
            if val
        ] if data["heart_rate"] else []),
        steptimes=array.array(
            'l',
            [int(val.split(',')[0]) for val in data["gait"].split(';')
             if val] if data["gait"] else []),
        stride=array.array(
            'l',
            [int(val.split(',')[2]) for val in data["gait"].split(';')
             if val] if data["gait"] else []),
        cadence=array.array(
            'l',
            [int(val.split(',')[3]) for val in data["gait"].split(';')
             if val] if data["gait"] else []),
    )
    return track_data


@click.option('-V',
              '--version',
              is_flag=True,
              callback=print_version,
              expose_value=False,
              is_eager=True,
              help='Print the current version number and exit.')
@click.group(invoke_without_command=True,
             cls=AliasedGroup,
             context_settings=CONTEXT_SETTINGS)
@click.argument('summary', type=click.Path(exists=True))
@click.argument('detail', type=click.Path(exists=True))
def cli(summary, detail):
    tracks = export_all_tracks(summary, detail)


def main():
    cli()
