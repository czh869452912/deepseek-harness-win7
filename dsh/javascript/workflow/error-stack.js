{
  const nativeErrorPrototype = Error.prototype
  const nativeDescriptor = Object.getOwnPropertyDescriptor(nativeErrorPrototype, 'stack')
  if (nativeDescriptor && nativeDescriptor.configurable && typeof nativeDescriptor.get === 'function') {
    Object.defineProperty(nativeErrorPrototype, 'stack', {
      ...nativeDescriptor,
      get() {
        const nativeStack = nativeDescriptor.get.call(this)
        if (typeof nativeStack !== 'string') return nativeStack
        const rendered = nativeErrorPrototype.toString.call(this)
        return nativeStack.startsWith(rendered + '\n') || nativeStack === rendered
          ? nativeStack : rendered + (nativeStack ? '\n' + nativeStack : '')
      },
    })
  }
}
