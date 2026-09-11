from __future__ import annotations
import dataclasses, time, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; SRC=ROOT/'src'; sys.path.insert(0,str(SRC))
import simulation_player_stat_fingerprints_v3 as fp
EXPECTED='player-fingerprint-runtime-cache-v1.0.1-2026-08-14'

@dataclasses.dataclass
class MutableSample:
    player_id: str
    ratings: dict[str,float]
    positions: list[str]
    workload: tuple[float,...]

class Unsafe:
    def __init__(self): self.value=1

def main()->int:
    checks={}; details={}
    checks['cache_v1_0_1_version_is_current']=getattr(fp,'PLAYER_FINGERPRINT_RUNTIME_CACHE_VERSION','')==EXPECTED
    checks['cache_v1_layer_is_preserved']=bool(getattr(fp,'_PLAYER_FINGERPRINT_RUNTIME_CACHE_V1',False))
    checks['uncached_reference_builder_is_preserved']=hasattr(fp,'_build_player_stat_fingerprint_uncached_v3')
    checks['recursive_v1_safety_oracle_is_preserved']=hasattr(fp,'_fingerprint_cache_key_v1')
    checks['fast_candidate_key_is_live']=hasattr(fp,'_fingerprint_cache_fast_candidate_key_v1_0_1')
    checks['public_builder_wraps_same_uncached_reference']=(getattr(fp.build_player_stat_fingerprint,'__wrapped__',None) is fp._build_player_stat_fingerprint_uncached_v3)

    sample=MutableSample('201939',{f'r{i}':float(i) for i in range(25)},['PG','SG'],tuple(i/10 for i in range(20)))
    before=fp._fingerprint_cache_fast_candidate_key_v1_0_1((sample,32.5),{'phase':'regular'})
    sample.ratings['r3']=999.0
    after=fp._fingerprint_cache_fast_candidate_key_v1_0_1((sample,32.5),{'phase':'regular'})
    checks['mutated_semantic_inputs_change_fast_key']=before!=after

    unsafe=Unsafe()
    authoritative=fp._fingerprint_cache_key_v1((unsafe,),{})
    checks['unknown_mutable_objects_still_fail_authoritative_safety_check']=(authoritative is fp._PLAYER_FINGERPRINT_CACHE_UNCACHEABLE_SENTINEL_V1)

    original=fp._build_player_stat_fingerprint_uncached_v3
    calls={'n':0}
    def fake(*args,**kwargs):
        calls['n']+=1
        return (str(args[0]), tuple(kwargs.items()))
    try:
        fp._build_player_stat_fingerprint_uncached_v3=fake
        fp.player_fingerprint_runtime_cache_clear_v1()
        a=fp.build_player_stat_fingerprint('201939',rating=91.0)
        b=fp.build_player_stat_fingerprint('201939',rating=91.0)
        info=fp.player_fingerprint_runtime_cache_info_v1()
        known_calls=calls['n']
        fp.player_fingerprint_runtime_cache_clear_v1(); calls['n']=0
        fp.build_player_stat_fingerprint(unsafe)
        unsafe.value=2
        fp.build_player_stat_fingerprint(unsafe)
        unsafe_calls=calls['n']
        unsafe_info=fp.player_fingerprint_runtime_cache_info_v1()
    finally:
        fp._build_player_stat_fingerprint_uncached_v3=original
        fp.player_fingerprint_runtime_cache_clear_v1()
    checks['known_input_cache_hit_is_exact']=a==b and known_calls==1 and int(info['hits'])==1 and int(info['misses'])==1
    checks['unknown_mutable_objects_still_bypass_cache']=unsafe_calls==2 and int(unsafe_info['hits'])==0 and int(unsafe_info['uncacheable'])>=2

    bench=MutableSample('201939',{f'r{i}':float(i) for i in range(30)},['PG','SG'],tuple(i/10 for i in range(24)))
    args=(bench,32.5,('regular',2026)); kwargs={'phase':'regular','tags':('a','b',3)}
    loops=12000
    t=time.perf_counter()
    for _ in range(loops): fp._fingerprint_cache_key_v1(args,kwargs)
    old=time.perf_counter()-t
    t=time.perf_counter()
    for _ in range(loops): fp._fingerprint_cache_fast_candidate_key_v1_0_1(args,kwargs)
    new=time.perf_counter()-t
    speed=old/max(new,1e-9)
    checks['fast_key_microbenchmark_is_materially_faster']=speed>=2.0
    details['fast_key_microbenchmark_is_materially_faster']=f'old={old:.4f}s fast={new:.4f}s speedup={speed:.2f}x'

    print('='*108); print('PLAYER FINGERPRINT RUNTIME CACHE V1.0.1 VALIDATION'); print('='*108)
    for k,v in checks.items(): print(f"  {k}: {'PASS' if v else 'FAIL'}"+(f" | {details[k]}" if k in details else ''))
    failed=[k for k,v in checks.items() if not v]
    if failed: raise AssertionError('Fingerprint Runtime Cache V1.0.1 failed: '+', '.join(failed))
    print('\nPLAYER FINGERPRINT RUNTIME CACHE V1.0.1 VALIDATION PASSED'); return 0
if __name__=='__main__': raise SystemExit(main())
