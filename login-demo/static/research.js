function normalizedEmail(value) {
  const email = String(value || '').trim();
  if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return '';
  return email;
}

export function customerEmailChoices(customers = []) {
  const seen = new Set();
  const choices = [];
  for (const customer of customers) {
    for (const [field, kind] of [['email', '主邮箱'], ['backup_email', '备用邮箱']]) {
      const email = normalizedEmail(customer?.[field]);
      const key = email.toLowerCase();
      if (!email || seen.has(key)) continue;
      seen.add(key);
      choices.push({
        value: `${customer.id}:${field}`,
        email,
        customerId: customer.id,
        customerName: String(customer.name || '').trim() || `客户 ${customer.id}`,
        kind,
      });
    }
  }
  return choices;
}

export function customerEmailChoice(choices = [], value = '') {
  return choices.find(choice => choice.value === value) || null;
}

export function preferredCustomerEmail(choices = [], customerId) {
  return choices.find(choice => String(choice.customerId) === String(customerId)) || null;
}
