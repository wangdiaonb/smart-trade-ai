import test from 'node:test';
import assert from 'node:assert/strict';
import {
  customerEmailChoice,
  customerEmailChoices,
  preferredCustomerEmail,
} from '../static/research.js';

test('customer email options come from primary and backup customer emails', () => {
  const choices = customerEmailChoices([
    {id: 7, name: 'Acme Pumps', email: 'alice@acme.example', backup_email: 'sales@acme.example'},
    {id: 8, name: 'No Email Buyer', email: '', backup_email: 'not-an-email'},
  ]);

  assert.deepEqual(choices.map(choice => choice.email), [
    'alice@acme.example',
    'sales@acme.example',
  ]);
  assert.equal(choices[0].customerId, 7);
  assert.equal(choices[1].kind, '备用邮箱');
});

test('customer email choices do not duplicate addresses across customers', () => {
  const choices = customerEmailChoices([
    {id: 1, name: 'First Buyer', email: 'buyer@example.com'},
    {id: 2, name: 'Second Buyer', email: 'BUYER@example.com'},
  ]);

  assert.equal(choices.length, 1);
  assert.equal(choices[0].customerName, 'First Buyer');
});

test('selecting a customer email resolves its customer relationship', () => {
  const choices = customerEmailChoices([
    {id: 4, name: 'Buyer Four', email: 'buyer4@example.com'},
  ]);

  assert.equal(customerEmailChoice(choices, '4:email').customerId, 4);
  assert.equal(preferredCustomerEmail(choices, '4').email, 'buyer4@example.com');
  assert.equal(customerEmailChoice(choices, 'missing'), null);
});
