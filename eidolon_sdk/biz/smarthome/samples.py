"""Sample homes a person can load from the mobile app to try things out.

`apartment` mirrors the home the laya smart-home evaluation uses
(eidolon_models/laya/evals/smart-home/homes/apartment.json), so a demo, the
rule interpreter's tests and the model evaluation all talk about the same
eighteen devices.
"""

from __future__ import annotations

from eidolon_sdk.biz.smarthome import Area, Command, Device, Registry, Scene


def _cmd(device_id: str, trait: str, command: str, **params) -> Command:
    return Command(device_id=device_id, trait=trait, command=command, params=params)


def apartment() -> Registry:
    areas = (
        Area(area_id="living", name="客厅", order=0),
        Area(area_id="master", name="主卧", order=1),
        Area(area_id="kitchen", name="厨房", order=2),
        Area(area_id="bath", name="卫生间", order=3),
        Area(area_id="balcony", name="阳台", order=4),
        Area(area_id="entry", name="玄关", order=5),
        Area(area_id="whole", name="全屋", order=6),
    )
    devices = (
        Device(device_id="living.main_light", name="客厅主灯", aliases=("大灯",), type="light", area_id="living"),
        Device(device_id="master.light", name="主卧灯", type="light", area_id="master"),
        Device(device_id="master.bedside", name="床头灯", aliases=("台灯",), type="light", area_id="master"),
        Device(device_id="living.ac", name="客厅空调", type="climate", area_id="living"),
        Device(device_id="master.ac", name="主卧空调", type="climate", area_id="master"),
        Device(device_id="living.curtain", name="客厅窗帘", type="cover", area_id="living"),
        Device(device_id="living.purifier", name="空气净化器", aliases=("净化器",), type="fan", area_id="living"),
        Device(device_id="master.humidifier", name="加湿器", type="fan", area_id="master"),
        Device(device_id="living.tv", name="电视", type="media", area_id="living"),
        Device(device_id="living.speaker", name="智能音箱", aliases=("音箱",), type="media", area_id="living"),
        Device(device_id="whole.vacuum", name="扫地机器人", aliases=("扫地机",), type="appliance", area_id="whole"),
        Device(device_id="balcony.washer", name="洗衣机", type="appliance", area_id="balcony"),
        Device(device_id="balcony.rack", name="电动晾衣架", aliases=("晾衣架",), type="cover", area_id="balcony"),
        Device(device_id="kitchen.rice_cooker", name="电饭煲", type="appliance", area_id="kitchen"),
        Device(device_id="bath.water_heater", name="热水器", type="water_heater", area_id="bath"),
        Device(device_id="entry.lock", name="智能门锁", aliases=("门锁",), type="lock", area_id="entry"),
        Device(device_id="entry.camera", name="摄像头", type="camera", area_id="entry"),
        Device(device_id="living.thermo", name="温湿度计", type="sensor", area_id="living"),
    )
    scenes = (
        Scene(
            scene_id="scene.home",
            name="回家",
            actions=(
                _cmd("living.main_light", "on_off", "on"),
                _cmd("living.main_light", "level", "set", value=70),
                _cmd("living.ac", "on_off", "on"),
                _cmd("living.ac", "thermostat", "set_target", celsius=26),
                _cmd("living.purifier", "on_off", "on"),
            ),
        ),
        Scene(
            scene_id="scene.away",
            name="离家",
            actions=(
                _cmd("living.main_light", "on_off", "off"),
                _cmd("master.light", "on_off", "off"),
                _cmd("master.bedside", "on_off", "off"),
                _cmd("living.ac", "on_off", "off"),
                _cmd("master.ac", "on_off", "off"),
                _cmd("living.tv", "on_off", "off"),
                _cmd("whole.vacuum", "operational", "start"),
                _cmd("entry.lock", "lock", "lock"),
            ),
        ),
        Scene(
            scene_id="scene.movie",
            name="观影",
            actions=(
                _cmd("living.main_light", "on_off", "on"),
                _cmd("living.main_light", "level", "set", value=15),
                _cmd("living.curtain", "position", "close"),
                _cmd("living.tv", "on_off", "on"),
            ),
        ),
        Scene(
            scene_id="scene.sleep",
            name="睡眠",
            actions=(
                _cmd("living.main_light", "on_off", "off"),
                _cmd("master.light", "on_off", "off"),
                _cmd("master.bedside", "on_off", "on"),
                _cmd("master.bedside", "level", "set", value=10),
                _cmd("master.ac", "on_off", "on"),
                _cmd("master.ac", "thermostat", "set_target", celsius=26),
                _cmd("living.curtain", "position", "close"),
                _cmd("living.tv", "on_off", "off"),
                _cmd("entry.lock", "lock", "lock"),
            ),
        ),
    )
    return Registry(revision=1, areas=areas, devices=devices, scenes=scenes)


SAMPLES = {"apartment": apartment}
