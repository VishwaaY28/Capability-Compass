import React from "react";
import { Link as RouterLink } from "react-router-dom";

export default function Hero() {
  return (
    <div className="min-h-screen bg-surface">
      <header className="bg-white/80 backdrop-blur-sm border-b">
        <div className="container mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <img src="/favicon.png" width={48} height={48} alt="Capability Compass" />
            <div>
              <h1 className="text-lg font-semibold">Capability Compass</h1>
              <p className="text-xs text-muted-foreground">Decide. Model. See the impact.</p>
            </div>
          </div>

          <nav className="flex items-center gap-6">
            <RouterLink to="/" className="text-sm font-medium text-foreground/90 hover:text-foreground">
              Home
            </RouterLink>
            <a href="#features" className="text-sm font-medium text-foreground/70 hover:text-foreground">
              Features
            </a>
            <a href="#about" className="text-sm font-medium text-foreground/70 hover:text-foreground">
              About
            </a>
            <a href="#contact" className="text-sm font-medium text-foreground/70 hover:text-foreground">
              Contact
            </a>
          </nav>
        </div>
      </header>

      <main className="container mx-auto px-6 py-16">
        <section className="grid grid-cols-1 lg:grid-cols-2 gap-12 items-center">

          <div className="space-y-6 max-w-xl">
              &nbsp;&nbsp;&nbsp;
            <h2 className="text-4xl font-bold leading-tight">Hexaware Capability Compass™</h2>
            <p className="text-lg text-muted-foreground">
              A Virtual Model Office that helps leaders reimagine enterprise capabilities
              and instantly see the downstream impact across value streams, processes,
              applications, APIs, and data.
              </p>
            <p className="text-lg text-muted-foreground">

                Built-in Decision Catalogs and industry-aligned capability frameworks let
                teams compare options, quantify KPI effects, and generate ready-to-deliver
                work packages — turning strategy into change with confidence.
              </p>
&nbsp;&nbsp;&nbsp;
            <div className="flex items-center gap-4 pt-4">
              <RouterLink to="/dashboard" className="inline-flex items-center px-6 py-3 bg-primary hover:bg-primary/90 text-white rounded-md">
                Get Started
              </RouterLink>
              <a href="#features" className="inline-flex items-center px-5 py-3 border rounded-md text-sm">
                Learn More
              </a>
                &nbsp;&nbsp;&nbsp;
            </div>
          </div>


          <div className="flex justify-center lg:justify-center">
            <div className="rounded-xl bg-gradient-to-tr from-primary/10 to-secondary/10 p-8 shadow-lg">
              <img src="/hero_logo.png" alt="Capability Compass" className="w-72 h-auto object-contain" />
            </div>
          </div>
        </section>
&nbsp;&nbsp;&nbsp;
        <section id="features" className="mt-16">
          <h3 className="text-2xl font-semibold mb-6">Key Features</h3>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div className="p-6 bg-card border rounded-lg">
              <h4 className="font-medium mb-2">What-if Analysis</h4>
              <p className="text-sm text-muted-foreground">Simulate capability changes and view KPI impact across the enterprise.</p>
            </div>
            <div className="p-6 bg-card border rounded-lg">
              <h4 className="font-medium mb-2">Decision Catalog</h4>
              <p className="text-sm text-muted-foreground">Curated decision templates and work packages to accelerate delivery.</p>
            </div>
            <div className="p-6 bg-card border rounded-lg">
              <h4 className="font-medium mb-2">Visualization</h4>
              <p className="text-sm text-muted-foreground">Interactive capability, process and application maps for clear communication.</p>
            </div>
          </div>
        </section>

        <section id="about" className="mt-16">
          <h3 className="text-2xl font-semibold mb-4">About</h3>
          <p className="text-sm text-muted-foreground max-w-3xl">
            Capability Compass brings together enterprise architecture, process models,
            and application inventories into a single decision workspace. Leaders and
            architects use it to align investments with business outcomes and to create
            executable plans.
          </p>
        </section>

        <section id="contact" className="mt-16">
          <h3 className="text-2xl font-semibold mb-4">Contact</h3>
          <p className="text-sm text-muted-foreground">For demos and trials, email <a className="text-primary" href="mailto:info@capabilitycompass.example">info@capabilitycompass.example</a></p>
        </section>
      </main>

      <footer className="border-t py-6 bg-white/60">
        <div className="container mx-auto px-6 text-sm text-muted-foreground flex items-center justify-between">
          <div>© {new Date().getFullYear()} Capability Compass</div>
          <div className="text-xs text-muted-foreground">Built for enterprise what-if analysis</div>
        </div>
      </footer>
    </div>
  );
}
