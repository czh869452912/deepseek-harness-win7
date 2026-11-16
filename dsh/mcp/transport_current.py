"""Current transport composition shared by supervisors and one-shot probes."""


def create_current_transport(config):
    kind = config.get('transport','stdio')
    if kind == 'stdio':
        from dsh.mcp.stdio_current import CurrentStdioMcpTransport
        return CurrentStdioMcpTransport(config.get('command','echo'),config.get('args',[]),config.get('env',{}),config.get('cwd',''))
    if kind == 'streamable-http':
        from dsh.mcp.http_current import CurrentStreamableHttpMcpTransport
        return CurrentStreamableHttpMcpTransport(config.get('url','http://localhost:8000'),config.get('headers',{}))
    raise ValueError("Unsupported transport: '"+str(kind)+"'")
