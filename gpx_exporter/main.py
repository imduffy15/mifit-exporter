import array
import datetime as DT
import sqlite3
from bisect import bisect_left
from collections import namedtuple
from datetime import datetime
from itertools import accumulate

import click
import xmltodict
from clickclick import AliasedGroup

import gpx_exporter

CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'])

NO_VALUE = -2000000

output_option = click.option('-o',
                             '--output',
                             type=click.Choice(['text', 'json', 'tsv']),
                             default='text',
                             help='Use alternative output format')

RawTrackData = namedtuple('RawTrackData', [
    'start_time', 'end_time', 'cost_time', 'distance', 'times', 'lat', 'lon',
    'alt', 'hrtimes', 'hr', 'steptimes', 'stride', 'cadence'
])
Position = namedtuple('Position', ['lat', 'lon', 'alt'])
TrackPoint = namedtuple('TrackPoint',
                        ['time', 'position', 'hr', 'stride', 'cadence'])


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


def export_all_tracks(conn):
    columns = (
        'TRACKDATA.TRACKID',
        'TRACKDATA.BULKLL',
        'TRACKDATA.BULKGAIT',
        'TRACKDATA.BULKAL',
        'TRACKDATA.BULKTIME',
        'TRACKDATA.BULKHR',
        'TRACKDATA.BULKPAUSE',
        'TRACKDATA.TYPE',
        'TRACKDATA.BULKFLAG',
        'TRACKRECORD.COSTTIME',
        'TRACKRECORD.ENDTIME',
        'TRACKRECORD.DISTANCE',
    )
    sql = """SELECT
        {columns}
        FROM TRACKDATA, TRACKRECORD
        WHERE TRACKDATA.TRACKID = TRACKRECORD.TRACKID
        ORDER BY TRACKDATA.TRACKID""".format(columns=', '.join(columns))
    RowRecord = namedtuple('RowRecord',
                           (col.split('.')[-1] for col in columns))
    try:
        for row in conn.execute(sql):
            row = RowRecord(*row)
            export_track_row(parse_track_data(row))
    except sqlite3.OperationalError:
        pass


def export_track_row(row):
    start_time = DT.datetime.utcfromtimestamp(row.start_time).isoformat()
    xml = {
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
                "trkseg": {
                    "trkpt": []
                }
            }
        }
    }
    for point in track_points(interpolate_data(row)):
        time = datetime.utcfromtimestamp(point.time +
                                         row.start_time).isoformat()
        trkpt = {
            "ele": point.position.alt,
            "time": time,
            "@lat": point.position.lat,
            "@lon": point.position.lon,
            "extensions": {
                "gpxtpx:TrackPointExtension": {}
            }
        }

        if point.hr:
            trkpt["extensions"]['gpxtpx:TrackPointExtension'][
                'gpxtpx:hr'] = point.hr

        if point.cadence:
            trkpt["extensions"]["gpxdata:cadence"] = point.cadence

        xml['gpx']['trk']['trkseg']['trkpt'].append(trkpt)
    click.echo(xmltodict.unparse(xml, pretty=True))


def interpolate_data(track_data):
    track_times = array.array('l', accumulate(track_data.times))
    hr_times = array.array('l', accumulate(track_data.hrtimes))
    step_times = array.array('l', accumulate(track_data.steptimes))

    times = list(sorted(set(track_times).union(hr_times).union(step_times)))

    return track_data._replace(
        times=times,
        lat=interpolate_column(accumulate(track_data.lat), track_times, times),
        lon=interpolate_column(accumulate(track_data.lon), track_times, times),
        alt=interpolate_column(track_data.alt, track_times, times),
        hrtimes=times,
        hr=interpolate_column(accumulate(track_data.hr), hr_times, times),
        steptimes=times,
        stride=interpolate_column(track_data.stride, step_times, times),
        cadence=interpolate_column(track_data.cadence, step_times, times),
    )


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
    for time, lat, lon, alt, hr, stride, cadence in zip(
            track_data.times, track_data.lat, track_data.lon, track_data.alt,
            track_data.hr, track_data.stride, track_data.cadence):
        yield TrackPoint(
            time=time,
            position=Position(lat=lat / 100000000,
                              lon=lon / 100000000,
                              alt=alt / 100),
            hr=hr,
            stride=stride,
            cadence=cadence,
        )


def parse_track_data(row):
    return RawTrackData(
        start_time=int(row.TRACKID),
        end_time=int(row.ENDTIME),
        cost_time=int(row.COSTTIME),
        distance=int(row.DISTANCE),
        times=array.array('l',
                          [int(val) for val in row.BULKTIME.split(';')
                           if val] if row.BULKTIME else []),
        lat=array.array(
            'l',
            [int(val.split(',')[0]) for val in row.BULKLL.split(';')
             if val] if row.BULKLL else []),
        lon=array.array(
            'l',
            [int(val.split(',')[1]) for val in row.BULKLL.split(';')
             if val] if row.BULKLL else []),
        alt=array.array('l',
                        [int(val) for val in row.BULKAL.split(';')
                         if val] if row.BULKAL else []),
        hrtimes=array.array('l', [
            int(val.split(',')[0] or 1) for val in row.BULKHR.split(';') if val
        ] if row.BULKHR else []),
        hr=array.array(
            'l',
            [int(val.split(',')[1]) for val in row.BULKHR.split(';')
             if val] if row.BULKHR else []),
        steptimes=array.array(
            'l',
            [int(val.split(',')[0]) for val in row.BULKGAIT.split(';')
             if val] if row.BULKGAIT else []),
        stride=array.array(
            'l',
            [int(val.split(',')[2]) for val in row.BULKGAIT.split(';')
             if val] if row.BULKGAIT else []),
        cadence=array.array(
            'l',
            [int(val.split(',')[3]) for val in row.BULKGAIT.split(';')
             if val] if row.BULKGAIT else []),
    )


# @click.option('-V',
#               '--version',
#               is_flag=True,
#               callback=print_version,
#               expose_value=False,
#               is_eager=True,
#               help='Print the current version number and exit.')
@click.group(invoke_without_command=True, cls=AliasedGroup, context_settings=CONTEXT_SETTINGS)
@click.argument('input-db', type=click.Path(exists=True))
@click.argument('output-file', type=click.Path(exists=False))
def cli(input_db, output_file):
    conn = sqlite3.connect(input_db)
    tracks = export_all_tracks(conn)
    conn.close()


def main():
    cli()
