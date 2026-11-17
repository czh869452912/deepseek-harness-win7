// Private UTC-wall enumeration only. No user JavaScript or zoned-library path.
globalThis.__receive = () => {};
globalThis.__drive = async () => {
  const query = __request.query;
  const basic = new Date(query.anchor).toISOString().replaceAll('-', '').replaceAll(':', '').slice(0, 15);
  const rule = rrule.rrulestr(`DTSTART:${basic}Z\n${query.recurrence}`);
  let result;
  if (query.mode === 'after') result = rule.after(new Date(query.from), true)?.getTime() ?? null;
  else {
    result = [];
    rule.all(date => {
      const wall = date.getTime();
      if (wall < query.from) return true;
      result.push(wall);
      return result.length < query.limit && (query.through === null || wall <= query.through);
    });
  }
  __emit(JSON.stringify({ type: 'terminal', result }));
};
