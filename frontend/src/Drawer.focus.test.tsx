import { useState } from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { CodeBlock, Drawer } from './ui';

describe('evidence Drawer keyboard containment', () => {
  it('wraps both directions through visible summaries instead of closed disclosure contents', async () => {
    const user = userEvent.setup();
    render(<Drawer title="Evidence" close={() => {}}>
      <CodeBlock title="Visible log" value="worker output" />
      <details><summary>Submitted configuration</summary><pre tabIndex={0}>hidden configuration</pre></details>
    </Drawer>);
    const close = screen.getByRole('button', { name: 'Close evidence' });
    const summary = screen.getByText('Submitted configuration');
    const log = screen.getByText('worker output').closest('pre');

    expect(close).toHaveFocus();
    await user.tab({ shift: true });
    expect(summary).toHaveFocus();
    await user.tab();
    expect(close).toHaveFocus();
    await user.tab();
    expect(log).toHaveFocus();
    await user.tab();
    expect(summary).toHaveFocus();
    await user.tab();
    expect(close).toHaveFocus();
  });

  it.each([
    ['hidden ancestor', <div hidden><pre tabIndex={0}>Unavailable</pre></div>],
    ['display-none ancestor', <div style={{ display: 'none' }}><pre tabIndex={0}>Unavailable</pre></div>],
    ['visibility-hidden ancestor', <div style={{ visibility: 'hidden' }}><pre tabIndex={0}>Unavailable</pre></div>],
    ['inert ancestor', <div inert><pre tabIndex={0}>Unavailable</pre></div>],
    ['disabled textarea', <textarea disabled defaultValue="Unavailable" />],
    ['disabled fieldset descendant', <fieldset disabled><input aria-label="Unavailable" /></fieldset>],
    ['disabled explicit tab stop', <button disabled tabIndex={0}>Unavailable</button>],
    ['hidden input', <input type="hidden" defaultValue="Unavailable" />],
    ['negative tab index', <button tabIndex={-1}>Unavailable</button>],
  ])('excludes a %s from both wrap boundaries', async (_name, unavailable) => {
    const user = userEvent.setup();
    render(<Drawer title="Evidence" close={() => {}}>
      <a href="#record">Last visible evidence</a>
      {unavailable}
    </Drawer>);
    const close = screen.getByRole('button', { name: 'Close evidence' });
    const last = screen.getByRole('link', { name: 'Last visible evidence' });

    await user.tab({ shift: true });
    expect(last).toHaveFocus();
    await user.tab();
    expect(close).toHaveFocus();
  });

  it('recomputes nested disclosure boundaries as evidence is expanded and collapsed', async () => {
    const user = userEvent.setup();
    render(<Drawer title="Evidence" close={() => {}}>
      <details><summary>Outer evidence</summary><pre tabIndex={0}>Outer log</pre>
        <details><summary>Inner evidence</summary><pre tabIndex={0}>Inner log</pre></details>
      </details>
    </Drawer>);
    const close = screen.getByRole('button', { name: 'Close evidence' });
    const outer = screen.getByText('Outer evidence');
    const inner = screen.getByText('Inner evidence');
    await user.tab({ shift: true });
    expect(outer).toHaveFocus();
    await user.click(outer);
    close.focus();
    await user.tab({ shift: true });
    expect(inner).toHaveFocus();
    await user.tab();
    expect(close).toHaveFocus();
    await user.click(inner);
    close.focus();
    await user.tab({ shift: true });
    expect(screen.getByText('Inner log')).toHaveFocus();
    await user.tab();
    expect(close).toHaveFocus();
    await user.click(outer);
    close.focus();
    await user.tab({ shift: true });
    expect(outer).toHaveFocus();
  });

  it('retains Escape dismissal, opener focus return and body scroll restoration', async () => {
    const user = userEvent.setup();
    const oldOverflow = document.body.style.overflow;
    function EvidenceLauncher() {
      const [open, setOpen] = useState(false);
      return <><button onClick={() => setOpen(true)}>Inspect record</button>{open && <Drawer title="Evidence" close={() => setOpen(false)}><details><summary>Configuration</summary><pre tabIndex={0}>Hidden</pre></details></Drawer>}</>;
    }
    render(<EvidenceLauncher />);
    const opener = screen.getByRole('button', { name: 'Inspect record' });
    await user.click(opener);
    expect(screen.getByRole('button', { name: 'Close evidence' })).toHaveFocus();
    expect(document.body.style.overflow).toBe('hidden');
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
    expect(document.body.style.overflow).toBe(oldOverflow);
  });
});
