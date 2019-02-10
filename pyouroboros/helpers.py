import requests

from threading import Thread
from queue import Queue

def set_properties(old, new, self_name=None):
    """Store object for spawning new container in place of the one with outdated image"""
    properties = {
        'name': self_name if self_name else old.name,
        'hostname': old.attrs['Config']['Hostname'],
        'user': old.attrs['Config']['User'],
        'domainname': old.attrs['Config']['Domainname'],
        'tty': old.attrs['Config']['Tty'],
        'ports': None if not old.attrs['Config'].get('ExposedPorts') else [
            (p.split('/')[0], p.split('/')[1]) for p in old.attrs['Config']['ExposedPorts'].keys()
        ],
        'volumes': None if not old.attrs['Config'].get('Volumes') else [
            v for v in old.attrs['Config']['Volumes'].keys()
        ],
        'working_dir': old.attrs['Config']['WorkingDir'],
        'image': new.tags[0],
        'command': old.attrs['Config']['Cmd'],
        'host_config': old.attrs['HostConfig'],
        'labels': old.attrs['Config']['Labels'],
        'entrypoint': old.attrs['Config']['Entrypoint'],
        'environment': old.attrs['Config']['Env'],
        # networks are conigured later
        'networking_config': None
    }

    return properties

def get_tags_from_registry(image_name, digest):
    if '/' not in image_name:
        # implemented according to the behaviour of docker itself:
        # https://github.com/moby/moby/blob/master/registry/session.go#L331
        image_name = 'library/{}'.format(image_name)

    res = requests.get(
        url='https://auth.docker.io/token?service=registry.docker.io&scope=repository:{}:pull'.format(image_name)
    )
    if res.status_code != 200:
        return []

    try:
        auth_code = res.json()['token']
    except ValueError:
        return []

    res = requests.get(
        url='https://registry.hub.docker.com/v2/{0}/tags/list'.format(image_name),
        headers={'Authorization': 'Bearer {}'.format(auth_code)}
    )
    try:
        res_json = res.json()
    except ValueError:
        return []

    tags_list = res_json.get('tags')
    if tags_list is None:
        return []

    queue = Queue()

    def request(image_name, auth_code, queue, tag, digest):
        res = requests.get(
            url='https://registry.hub.docker.com/v2/{0}/manifests/{1}'.format(image_name, tag),
            headers={
                'Authorization': 'Bearer {}'.format(auth_code),
                'Accept': 'application/vnd.docker.distribution.manifest.v2+json'
            }
        )

        if res.status_code != 200:
            return

        tag_digest = res.json().get('config', {}).get('digest')

        if tag_digest == digest:
            queue.put(tag)

    num_threads = 100

    for i in range(0, len(tags_list), num_threads):
        threads = []

        #print('Processing {}'.format(tags_list[i:i+num_threads]))
        for tag in tags_list[i:i+num_threads]:
            threads.append(Thread(target=request, args=(image_name, auth_code, queue, tag, digest)))

        for t in threads:
            t.start()

        for t in threads:
            t.join()

    #print('Processed {} tags'.format(str(len(tags_list))))

    return [queue.get(i) for i in range(queue.qsize())]