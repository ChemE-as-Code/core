<script setup lang="ts">
// Served from public/ so the logo can be swapped without a rebuild; BASE_URL keeps it working in a static snapshot.
const logo = `${import.meta.env.BASE_URL}logo.svg`;

const groupLinks = [
  { label: "Group website", url: "https://www.pi-research.org/" },
  { label: "GitHub", url: "https://github.com/process-intelligence-research" },
  { label: "LinkedIn", url: "https://www.linkedin.com/company/84022065/" },
];
const personLinks = [
  { label: "TU Delft profile", url: "https://www.tudelft.nl/tnw/over-faculteit/afdelingen/chemical-engineering/principal-scientists/artur-schweidtmann" },
  { label: "Google Scholar", url: "https://scholar.google.com/citations?user=g-GwouoAAAAJ" },
  { label: "ORCID", url: "https://orcid.org/0000-0001-8885-6847" },
  { label: "LinkedIn", url: "https://www.linkedin.com/in/schweidtmann/" },
];
</script>

<template>
  <div class="page about">
    <div class="hero">
      <img class="logo" :src="logo" alt="ChemE-as-Code logo" width="96" height="96" data-testid="about-logo" />
      <div>
        <h1>ChemE-as-Code</h1>
        <p class="muted lead">Chemical plant engineering as code: P&amp;IDs, process data, layout and life cycle assessment in a git repository, checked and reviewed like software.</p>
      </div>
    </div>

    <h2>Developed by</h2>
    <div class="cards">
      <section class="card" data-testid="about-group">
        <strong>Process Intelligence Research</strong>
        <span>Department of Chemical Engineering, Faculty of Applied Sciences, Delft University of Technology</span>
        <p class="muted">AI for chemical engineering: generative AI for engineering diagrams, AI-assisted HAZOP, hybrid and constrained machine learning, optimization and multi-agent systems, together with industry.</p>
        <ul class="links">
          <li v-for="l in groupLinks" :key="l.url"><a :href="l.url" target="_blank" rel="noopener">{{ l.label }}</a></li>
        </ul>
      </section>
      <section class="card" data-testid="about-person">
        <strong>Artur M. Schweidtmann</strong>
        <span>Tenured Assistant Professor, head of Process Intelligence Research</span>
        <p class="muted"><a href="mailto:a.schweidtmann@tudelft.nl">a.schweidtmann@tudelft.nl</a></p>
        <ul class="links">
          <li v-for="l in personLinks" :key="l.url"><a :href="l.url" target="_blank" rel="noopener">{{ l.label }}</a></li>
        </ul>
      </section>
    </div>

    <h2>Software</h2>
    <ul class="links">
      <li><a href="https://github.com/ChemE-as-Code" target="_blank" rel="noopener">ChemE-as-Code on GitHub</a> (core, viewer, examples)</li>
      <li>Licence: AGPL-3.0-or-later</li>
    </ul>
  </div>
</template>

<style scoped>
.about {
  max-width: 960px;
}
.hero {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  margin-bottom: var(--space-4);
}
.hero h1 {
  margin-bottom: var(--space-1);
}
.lead {
  margin: 0;
}
.logo {
  flex: none;
}
h2 {
  font-size: var(--text);
  margin: var(--space-6) 0 var(--space-2);
}
.cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: var(--space-3);
}
.card {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  padding: var(--space-4);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
}
.card p {
  margin: var(--space-1) 0 0;
}
.links {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1) var(--space-3);
  list-style: none;
  margin: var(--space-2) 0 0;
  padding: 0;
}
@media (max-width: 480px) {
  .hero {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
