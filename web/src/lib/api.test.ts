import { describe, it, expect } from 'vitest';
import { API_BASE } from './api';

describe('api module', () => {
  it('exports a base URL string', () => {
    expect(typeof API_BASE).toBe('string');
    expect(API_BASE.length).toBeGreaterThan(0);
  });
});
