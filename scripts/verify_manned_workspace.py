"""Read-only checks for local data and migrated baseline; no data rebuilding."""
from pathlib import Path
import importlib.metadata
import json
import subprocess
import sys

import geopandas as gpd
import pyarrow.parquet as pq
import rasterio
import yaml
from rasterio.windows import Window

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
import h3_offroad_planner
from h3_offroad_planner.desktop_project import load_project_yaml


def main():
    assets=yaml.safe_load((ROOT/'configs/manned_assets.private.yaml').read_text(encoding='utf-8'))
    project=load_project_yaml(ROOT/'configs/manned_offroad.local.private.yaml')
    unsupported=project.unsupported_fields()
    assert not unsupported,unsupported
    report={'python':sys.executable,'python_version':sys.version.split()[0],
            'module_file':h3_offroad_planner.__file__,
            'head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            'branch':subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip(),
            'dependencies':{},'rasters':{},'vectors':{},'static_moisture':[],
            'desktop_project_unsupported_fields':unsupported}
    assert Path(h3_offroad_planner.__file__).resolve().is_relative_to(ROOT/'src')
    if project.route.get('environment_snapshot_path'):
        from h3_offroad_planner.factor_model import load_static_planning_config
        from h3_offroad_planner.environment import load_environment_snapshot
        route=project.route
        config=load_static_planning_config(route['static_planning_path'])
        weather=load_environment_snapshot(route['environment_snapshot_path'],config.weather,
            (route['start_lat']+route['goal_lat'])/2,
            (route['start_lng']+route['goal_lng'])/2)
        assert not weather.degraded
        report['frozen_weather']={'valid_at':weather.valid_at,'degraded':weather.degraded,
            'path':route['environment_snapshot_path']}
    for name in ['h3','numpy','pandas','geopandas','shapely','rasterio','pyarrow','PyYAML','pytest','PyQt5','PyQtWebEngine']:
        report['dependencies'][name]=importlib.metadata.version(name)
    for name in ['dem','orthophoto','soil']:
        path=Path(assets[name])
        with rasterio.open(path) as dataset:
            a=dataset.read(1,window=Window(dataset.width//2,dataset.height//2,1,1),masked=True)
            report['rasters'][name]={'path':path.as_posix(),'crs':str(dataset.crs),
                'shape':[dataset.height,dataset.width],'bands':dataset.count,
                'pixel_size':list(dataset.res),'bounds':list(dataset.bounds),
                'center_sample':None if a.mask.all() else float(a.item())}
    vector_paths=list(Path(assets['landcover_directory']).glob('*.shp'))+[Path(assets['road'])]
    for path in vector_paths:
        frame=gpd.read_file(path)
        attr={}
        for col in frame.columns:
            if any(key in col.lower() for key in ['row','spac','width','depth']):
                series=frame[col].dropna()
                attr[col]={'non_null':int(series.size),'sample':series.head(5).astype(str).tolist()}
        report['vectors'][path.stem]={'path':path.as_posix(),'features':len(frame),
            'crs':str(frame.crs),'columns':[c for c in frame.columns if c!='geometry'],'attributes':attr}
    catalog=gpd.read_file(assets['soil_catalog'])
    report['soil_catalog']={'rows':len(catalog),'columns':list(catalog.columns)}
    for filename in assets['static_moisture']:
        # NetCDF metadata + actual small band read through the installed GDAL driver.
        with rasterio.open(filename) as root:
            subdatasets=root.subdatasets
            selected=subdatasets[0] if subdatasets else filename
        with rasterio.open(selected) as ds:
            ds.read(1,window=Window(ds.width//2,ds.height//2,1,1))
            report['static_moisture'].append({'path':filename,'shape':[ds.height,ds.width],
                'subdatasets':subdatasets,'tags':ds.tags(),'bands':ds.count})
    report['hydrology']={}
    for name,filename in assets['hydrology'].items():
        with rasterio.open(filename) as ds:
            ds.read(1,window=Window(ds.width//2,ds.height//2,1,1))
            report['hydrology'][name]={'path':filename,'shape':[ds.height,ds.width],'crs':str(ds.crs)}
    manifest=Path(assets['baseline_manifest'])
    data=json.loads(manifest.read_text(encoding='utf-8'))
    paths=[]
    def collect(value):
        if isinstance(value,dict):
            for key,item in value.items():
                if key=='path' and isinstance(item,str) and item.endswith('.parquet'): paths.append(Path(item))
                elif isinstance(item,(dict,list)):collect(item)
        elif isinstance(value,list):
            for item in value:collect(item)
    collect(data)
    assert paths,'No tile parquet references found'
    missing=[str(p) for p in paths if not p.exists()]
    assert not missing,missing[:5]
    assert all(p.resolve().is_relative_to(ROOT/'outputs') for p in paths)
    sample=pq.read_table(paths[0])
    report['baseline_tiles']={'manifest':str(manifest),'cells_count':data.get('cells_count'),
        'edges_count':data.get('edges_count'),'referenced_files':len(paths),'missing_files':len(missing),
        'sample_file':str(paths[0]),'sample_rows':sample.num_rows,'sample_columns':sample.column_names}
    report['input_wiring']={'orthophoto':'Local raster readable; source GUI provides online basemap, not a local GeoTIFF layer.',
        'static_moisture':'Local CLDAS files readable and registered; M1 physical integration still pending.',
        'hydrology':'Existing upstream-domain rasters registered; baseline cache kept unchanged.',
        'private_map_config_present':(ROOT/'configs/map.private.yaml').exists()}
    destination=ROOT/'.artifacts/workspace-preparation/data_check.json'
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    print(json.dumps({'status':'passed','python':report['python'],'module_file':report['module_file'],
        'vector_layers':len(report['vectors']),'raster_layers':len(report['rasters']),
        'moisture_files':len(report['static_moisture']),'hydrology_layers':len(report['hydrology']),
        'tile_references':len(paths),'report':str(destination)},ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
