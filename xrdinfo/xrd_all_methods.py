#!/usr/bin/python3

from threading import Thread, Event
import argparse
import xrdinfo
import queue
import sys

# By default return listMethods
DEFAULT_METHOD = 'listMethods'

# Default timeout for HTTP requests
DEFAULT_TIMEOUT = 5.0

# Do not use threading by default
DEFAULT_THREAD_COUNT = 1


def print_error(content):
    """Error printer."""
    content = "ERROR: {}\n".format(content)
    sys.stderr.write(content)


def worker(params):
    while True:
        # Checking periodically if it is the time to gracefully shutdown
        # the worker.
        try:
            subsystem = params['work_queue'].get(True, 0.1)
        except queue.Empty:
            if params['shutdown'].is_set():
                return
            else:
                continue
        try:
            if params['rest']:
                for method in xrdinfo.methods_rest(
                        addr=params['url'], client=params['client'], producer=subsystem,
                        method=params['method'], timeout=params['timeout'], verify=params['verify'],
                        cert=params['cert']):
                    line = xrdinfo.identifier(method) + '\n'
                    # Using thread safe "write" instead of "print"
                    sys.stdout.write(line)
            else:
                for method in xrdinfo.methods(
                        addr=params['url'], client=params['client'], producer=subsystem,
                        method=params['method'], timeout=params['timeout'],
                        verify=params['verify'],
                        cert=params['cert']):
                    line = xrdinfo.identifier(method) + '\n'
                    # Using thread safe "write" instead of "print"
                    sys.stdout.write(line)
        except Exception as e:
            print_error('{}: {}'.format(type(e).__name__, e))
        finally:
            params['work_queue'].task_done()


def main():
    parser = argparse.ArgumentParser(
        description='X-Road listMethods request to all members.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='By default peer TLS certificate is not validated.'
    )
    parser.add_argument(
        'url', metavar='SERVER_URL',
        help='URL of local Security Server accepting X-Road requests.')
    parser.add_argument(
        'client', metavar='CLIENT',
        help='Client identifier consisting of slash separated Percent-Encoded parts (e.g. '
             '"INSTANCE/MEMBER_CLASS/MEMBER_CODE/SUBSYSTEM_CODE" '
             'or "INSTANCE/MEMBER_CLASS/MEMBER_CODE").')
    parser.add_argument('-t', metavar='TIMEOUT', help='timeout for HTTP query', type=float)
    parser.add_argument('--allowed', help='return only allowed methods', action='store_true')
    parser.add_argument('--rest', help='return REST methods instead of SOAP', action='store_true')
    parser.add_argument('--threads', metavar='THREADS', help='amount of threads to use', type=int)
    parser.add_argument(
        '--verify', metavar='CERT_PATH',
        help='validate peer TLS certificate using CA certificate file.')
    parser.add_argument(
        '--cert', metavar='CERT_PATH', help='use TLS certificate for HTTPS requests.')
    parser.add_argument('--key', metavar='KEY_PATH', help='private key for TLS certificate.')
    parser.add_argument(
        '--instance', metavar='INSTANCE',
        help='use this instance instead of local X-Road instance.')
    args = parser.parse_args()

    params = {
        'url': args.url,
        'client': xrdinfo.identifier_parts(args.client),
        'method': DEFAULT_METHOD,
        'instance': None,
        'timeout': DEFAULT_TIMEOUT,
        'verify': False,
        'cert': None,
        'rest': args.rest,
        'thread_cnt': DEFAULT_THREAD_COUNT,
        'work_queue': queue.Queue(),
        'shutdown': Event()
    }

    if not (len(params['client']) in (3, 4)):
        print_error('Client name is incorrect: "{}"'.format(args.client))
        exit(1)

    if args.allowed:
        params['method'] = 'allowedMethods'

    if args.instance:
        params['instance'] = args.instance

    if args.t:
        params['timeout'] = args.t

    if args.verify:
        params['verify'] = args.verify

    if args.cert and args.key:
        params['cert'] = (args.cert, args.key)

    if args.threads and args.threads > 0:
        params['thread_cnt'] = args.threads

    shared_params = None
    try:
        shared_params = xrdinfo.shared_params_ss(
            addr=args.url, instance=params['instance'], timeout=params['timeout'],
            verify=params['verify'], cert=params['cert'])
    except xrdinfo.XrdInfoError as e:
        print_error('Cannot download Global Configuration: {}'.format(e))
        exit(1)

    # Create and start new threads
    threads = []
    for _ in range(params['thread_cnt']):
        t = Thread(target=worker, args=(params,))
        t.daemon = True
        t.start()
        threads.append(t)

    # Populate the queue
    try:
        for subsystem in xrdinfo.registered_subsystems(shared_params):
            params['work_queue'].put(subsystem)
    except xrdinfo.XrdInfoError as e:
        print_error(e)
        exit(1)

    # Block until all tasks in queue are done
    params['work_queue'].join()

    # Set shutdown event and wait until all daemon processes finish
    params['shutdown'].set()
    for t in threads:
        t.join()


if __name__ == '__main__':
    main()
