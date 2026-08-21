package bgpersist

import (
	"context"
	"sync"
)

// Pool bounds async persist goroutines.
type Pool struct {
	sem chan struct{}
	wg  sync.WaitGroup
}

func New(max int) *Pool {
	if max < 1 {
		max = 4
	}
	return &Pool{sem: make(chan struct{}, max)}
}

func (p *Pool) Submit(ctx context.Context, fn func(context.Context)) {
	p.wg.Add(1)
	go func() {
		defer p.wg.Done()
		select {
		case p.sem <- struct{}{}:
			defer func() { <-p.sem }()
		case <-ctx.Done():
			return
		}
		fn(ctx)
	}()
}

func (p *Pool) Wait() { p.wg.Wait() }
