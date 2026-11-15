"""Read configured TLS bytes once and join executor ownership before retiring."""
import asyncio
import os
import ssl
import tempfile


def read_tls_file(field, path):
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as handle:
            content = handle.read()
    except OSError as error:
        raise ValueError('webserver: cannot read tls.{} {}: {}'.format(field, path, error)) from error
    if not content.strip():
        raise ValueError('webserver: tls.{} {} is empty'.format(field, path))
    return content


def load_tls_context(cert_file, key_file, cert, key):
    try:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        # Python's SSL API requires paths. Materialize only the captured bytes,
        # then immediately unlink the private owned copies after OpenSSL loads.
        with tempfile.TemporaryDirectory(prefix='dsh-tls-') as directory:
            paths = [os.path.join(directory, name) for name in ('cert.pem', 'key.pem')]
            for path, text in zip(paths, (cert, key)):
                with open(path, 'w', encoding='utf-8') as handle:
                    handle.write(text)
            def no_passphrase():
                raise ValueError('encrypted private keys require a passphrase')
            context.load_cert_chain(*paths, password=no_passphrase)
        return context
    except (OSError, ValueError) as error:
        raise ValueError('webserver: tls.certFile {} and tls.keyFile {} are not a usable certificate and key pair: {}'.format(cert_file, key_file, error)) from error


async def prepare_tls(config):
    cert_file, key_file = (os.path.abspath(config[field]) for field in ('certFile', 'keyFile'))
    loop = asyncio.get_running_loop()
    pending = asyncio.gather(*(loop.run_in_executor(None, read_tls_file, field, path)
                               for field, path in (('certFile', cert_file), ('keyFile', key_file))), return_exceptions=True)
    try:
        values = await asyncio.shield(pending)
    except asyncio.CancelledError:
        await pending
        raise
    for value in values:
        if isinstance(value, BaseException):
            raise value
    return load_tls_context(cert_file, key_file, *values)
